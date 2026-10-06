"""Running an experiment: a LangGraph pipeline per question and variant.

    retrieve -> assemble_prompt -> generate -> evaluate -> record

- retrieve: the variant's retrieval strategy and top_k over the experiment's
  documents, reranked if the variant says so (see retrieval.retrieve);
- assemble_prompt: the variant's prompt (built-in or a library version)
  around the numbered passages, as in chat;
- generate: the variant's provider and model, with the user's key;
- evaluate: the experiment's evaluator (the built-in LLM judge, Ragas or
  DeepEval; if it asks for scores) and ROUGE-L against the reference answer
  (if there is one);
- record: one ExperimentResult row.

A failure in retrieve or generate skips straight to record, which stores the
error; a failed evaluation keeps the answer. Retrieval that ran, but not as
the variant says (its reranker or an embedding model could not be used), is
noted in the result's error too, so it never passes for the real thing. The run goes on with the next
question either way, so one bad call never loses the rest of the run.

The run claims the experiment with a token, like indexing does: if the
experiment is re-run or deleted meanwhile, this run stops at its next
result. It runs synchronously (in a Celery worker or a background thread);
the provider calls, which are async, run on a private event loop.

Up to `experiment.concurrency` answers are worked on at once, each in its
own thread with its own database session and pipeline. Results are stored
by question and variant, so the order they finish in does not matter.
Provider calls that hit a rate limit or a passing error wait and are tried
again (see llm.retry), which is what makes running several at once safe.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.core import tracing
from app.core.config import settings
from app.db.database import SessionLocal
from app.models.experiment import Experiment, ExperimentResult, ExperimentVariant
from app.services import telemetry
from app.services.chat_service import build_prompt, extract_citations, prompt_template
from app.services.llm import ProviderError, ProviderFactory, Usage, complete, create_provider, get_spec
from app.services.llm.pricing import estimate_cost_usd
from app.services.llm.retry import RetryingReranker, with_retries
from app.services.provider_key import MissingProviderKeyError, create_user_provider
from app.services import embedding_service, rag_evaluation, reranking
from app.services.evaluators import EvaluationError, EvaluationInput
from app.services.retrieval import RetrievedChunk, retrieve
from app.services.rouge_scoring import score_rouge_l

logger = logging.getLogger(__name__)


class CaseState(TypedDict, total=False):
    case_index: int
    question: str
    reference: str | None
    variant_id: int
    sources: list[RetrievedChunk]
    messages: list
    answer: str
    model: str
    usage: Usage
    latency_ms: float
    scores: dict
    error: str
    # Retrieval ran, but not as the variant says (a reranker or an embedding
    # model could not be used): stored with the result as its error.
    warnings: list[str]


class _Superseded(Exception):
    """The experiment was re-run or deleted while this run was going."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _context(sources: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "number": i,
            "document_id": s.document_id,
            "document_title": s.document_title,
            "page_number": s.page_number,
            "chunk_id": s.chunk_id,
            "content": s.content,
        }
        for i, s in enumerate(sources, start=1)
    ]


def _complete(provider, messages, model: str, max_tokens: int):
    return asyncio.run(complete(provider, messages, model, max_tokens))


def build_graph(
    session: Session,
    experiment: Experiment,
    token: str,
    factory: ProviderFactory,
    retriever: Callable[..., list[RetrievedChunk]],
):
    """The compiled pipeline for one experiment run; invoke it once per question and variant."""
    user_id = experiment.user_id
    variants: dict[int, ExperimentVariant] = {v.id: v for v in experiment.variants}
    templates: dict[int, str | None] = {}

    def template_for(variant: ExperimentVariant) -> str | None:
        if variant.id not in templates:
            templates[variant.id] = (
                prompt_template(session, user_id, variant.prompt_version_id) if variant.prompt_version_id else None
            )
        return templates[variant.id]

    def retrying_reranker(session_, user_id_, choice):
        # Concurrent runs can hit a rerank API's rate limit too.
        return RetryingReranker(reranking.build_reranker(session_, user_id_, choice))

    def retrieve_node(state: CaseState) -> dict:
        variant = variants[state["variant_id"]]
        warnings: list[str] = []
        try:
            sources = retriever(
                session, user_id, state["question"], k=variant.top_k,
                document_ids=experiment.document_ids, strategy=variant.retrieval, rerank=variant.rerank,
                warnings=warnings, reranker_factory=retrying_reranker,
            )
        except Exception as exc:
            logger.exception("Experiment retrieval failed", extra={"experiment_id": experiment.id})
            return {"error": f"Retrieval failed: {type(exc).__name__}"}
        return {"sources": sources, "warnings": warnings}

    def assemble_prompt_node(state: CaseState) -> dict:
        variant = variants[state["variant_id"]]
        return {"messages": build_prompt([], state["question"], state["sources"], template_for(variant))}

    def generate_node(state: CaseState) -> dict:
        variant = variants[state["variant_id"]]
        prompt_text = "\n\n".join(m.content for m in state["messages"])
        try:
            provider = create_user_provider(session, user_id, variant.provider, factory)
        except MissingProviderKeyError:
            return {"error": f"No API key stored for provider '{variant.provider}'."}
        started = time.perf_counter()
        try:
            result = _complete(provider, state["messages"], variant.model, settings.llm_max_output_tokens)
        except ProviderError as exc:
            telemetry.record_llm_call(
                session, user_id=user_id, operation="experiment", provider=variant.provider, model=variant.model,
                latency_ms=(time.perf_counter() - started) * 1000, error=exc, prompt_text=prompt_text,
            )
            return {"error": exc.message}
        latency_ms = (time.perf_counter() - started) * 1000
        model = result.model or variant.model
        event = telemetry.record_llm_call(
            session, user_id=user_id, operation="experiment", provider=variant.provider, model=model,
            latency_ms=latency_ms, usage=result.usage, prompt_text=prompt_text, completion_text=result.text,
        )
        usage = Usage(event.prompt_tokens, event.completion_tokens)
        return {"answer": result.text, "model": model, "usage": usage, "latency_ms": latency_ms}

    embedders: list = []

    def embedder_for_ragas():
        # The user's embedding model, built once per run (Ragas's answer relevancy embeds).
        if not embedders:
            embedders.append(rag_evaluation.user_embedder(session, user_id))
        return embedders[0]

    def evaluate_node(state: CaseState) -> dict:
        variant = variants[state["variant_id"]]
        reference = state.get("reference")
        scores: dict = {"rouge_l": score_rouge_l(state["answer"], reference) if reference else None}
        if not experiment.evaluate:
            return {"scores": scores}
        judge_provider = experiment.judge_provider or variant.provider
        judge_model = experiment.judge_model or (
            variant.model if judge_provider == variant.provider else get_spec(judge_provider).default_model
        )
        item = EvaluationInput(
            question=state["question"],
            answer=state["answer"],
            contexts=[s.content for s in state["sources"]],
            reference=reference,
        )
        judge = None
        try:
            judge = rag_evaluation.resolve_judge(session, user_id, judge_provider, judge_model, factory)
            embedder = embedder_for_ragas() if experiment.evaluator == "ragas" else None
            judged = asyncio.run(rag_evaluation.score(item, judge, experiment.evaluator, embedder))
        except EvaluationError as exc:
            return {"scores": scores, "error": f"Evaluation failed: {exc.message}"}
        finally:
            if judge is not None:
                rag_evaluation.record_judge_calls(session, user_id, judge)
            if embedders:
                embedding_service.record_calls(session, user_id, embedders[0])
        scores.update(
            faithfulness=judged.faithfulness,
            answer_relevancy=judged.answer_relevancy,
            context_precision=judged.context_precision,
            context_recall=judged.context_recall if reference else None,
            hallucination=judged.hallucination_score(),
            judge_rationale=judged.rationale,
        )
        return {"scores": scores}

    def record_node(state: CaseState) -> dict:
        # Write only while this run still owns the experiment. The row lock
        # (PostgreSQL) keeps a re-run from taking over between this check and
        # the commit: start_run takes the same lock before it deletes results.
        owner = (
            session.query(Experiment.run_token).filter(Experiment.id == experiment.id).with_for_update().scalar()
        )
        if owner != token:
            session.rollback()
            raise _Superseded()
        sources = state.get("sources") or []
        answer = state.get("answer")
        usage = state.get("usage") or Usage()
        scores = state.get("scores") or {}
        session.add(
            ExperimentResult(
                experiment_id=experiment.id,
                variant_id=state["variant_id"],
                case_index=state["case_index"],
                answer=answer,
                citations=extract_citations(answer, sources) if answer else None,
                context=_context(sources) if sources else None,
                latency_ms=round(state["latency_ms"], 2) if "latency_ms" in state else None,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost_usd=estimate_cost_usd(state.get("model"), usage) if answer is not None else None,
                faithfulness=scores.get("faithfulness"),
                answer_relevancy=scores.get("answer_relevancy"),
                context_precision=scores.get("context_precision"),
                context_recall=scores.get("context_recall"),
                hallucination=scores.get("hallucination"),
                rouge_l=scores.get("rouge_l"),
                judge_rationale=scores.get("judge_rationale"),
                error="\n".join(filter(None, [*state.get("warnings", []), state.get("error")]))[:2000] or None,
                created_at=_now(),
            )
        )
        session.commit()
        return {}

    def after_retrieve(state: CaseState) -> str:
        return "record" if state.get("error") else "assemble_prompt"

    def after_generate(state: CaseState) -> str:
        return "record" if state.get("error") else "evaluate"

    def traced(name: str, node):
        # One span per pipeline step, inside the case's span (see run_experiment).
        def run(state: CaseState) -> dict:
            with tracing.span(f"experiment.{name}") as current:
                update = node(state)
                if update.get("error"):
                    current.set_attribute("experiment.error", update["error"][:500])
                return update

        return run

    graph = StateGraph(CaseState)
    graph.add_node("retrieve", traced("retrieve", retrieve_node))
    graph.add_node("assemble_prompt", traced("assemble_prompt", assemble_prompt_node))
    graph.add_node("generate", traced("generate", generate_node))
    graph.add_node("evaluate", traced("evaluate", evaluate_node))
    graph.add_node("record", traced("record", record_node))
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", after_retrieve, ["assemble_prompt", "record"])
    graph.add_edge("assemble_prompt", "generate")
    graph.add_conditional_edges("generate", after_generate, ["evaluate", "record"])
    graph.add_edge("evaluate", "record")
    graph.add_edge("record", END)
    return graph.compile()


def _claim(session: Session, experiment_id: int, token: str) -> Experiment | None:
    claimed = (
        session.query(Experiment)
        .filter(Experiment.id == experiment_id, Experiment.status == "queued")
        .update(
            {Experiment.status: "running", Experiment.run_token: token, Experiment.started_at: _now()},
            synchronize_session=False,
        )
    )
    session.commit()
    return session.get(Experiment, experiment_id) if claimed else None


def _invoke(graph, experiment: Experiment, case_index: int, case: dict, variant: ExperimentVariant) -> None:
    """Answer one question with one variant (its result is stored by the graph's record step)."""
    with tracing.span(
        "experiment.case", experiment__id=experiment.id, experiment__case=case_index,
        experiment__variant=variant.label, gen_ai__system=variant.provider,
        gen_ai__request__model=variant.model, retrieval__strategy=variant.retrieval, retrieval__rerank=variant.rerank,
        user__id=str(experiment.user_id),
    ):
        graph.invoke(
            {
                "case_index": case_index,
                "question": case["question"],
                "reference": case.get("reference_answer"),
                "variant_id": variant.id,
            }
        )


def _run_parallel(
    experiment_id: int,
    work: list[tuple[int, dict, int]],
    workers: int,
    token: str,
    session_factory: Callable[[], Session],
    factory: ProviderFactory,
    retriever: Callable[..., list[RetrievedChunk]],
) -> None:
    """Work through (case index, case, variant id) items on `workers` threads.

    Each thread has its own session, experiment and graph: sessions and the
    objects loaded through them are not shared between threads. The first
    failure (or a newer run taking over) stops the items not yet started,
    and is raised once the running ones have finished.
    """
    local = threading.local()
    sessions: list[Session] = []
    lock = threading.Lock()
    stop = threading.Event()

    def context():
        if not hasattr(local, "graph"):
            session = session_factory()
            with lock:
                sessions.append(session)
            experiment = session.get(Experiment, experiment_id)
            if experiment is None or experiment.run_token != token:
                raise _Superseded()
            local.experiment = experiment
            local.variants = {v.id: v for v in experiment.variants}
            local.graph = build_graph(session, experiment, token, factory, retriever)
        return local

    def task(case_index: int, case: dict, variant_id: int) -> None:
        if stop.is_set():
            return
        try:
            ctx = context()
            _invoke(ctx.graph, ctx.experiment, case_index, case, ctx.variants[variant_id])
        except BaseException:
            stop.set()
            raise

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"experiment-{experiment_id}") as pool:
            futures = [pool.submit(task, *item) for item in work]
        errors = [future.exception() for future in futures if future.exception() is not None]
    finally:
        for session in sessions:
            session.close()
    for error in errors:
        if isinstance(error, _Superseded):
            raise error
    if errors:
        raise errors[0]


def run_experiment(
    experiment_id: int,
    session_factory: Callable[[], Session] = SessionLocal,
    factory: ProviderFactory = create_provider,
    retriever: Callable[..., list[RetrievedChunk]] = retrieve,
) -> None:
    """Answer every question with every variant and store the results.

    Never raises: an unexpected failure marks the experiment failed.
    """
    from app.services.experiment_service import MAX_CONCURRENCY

    token = str(uuid.uuid4())
    factory = with_retries(factory)
    session = session_factory()
    try:
        experiment = _claim(session, experiment_id, token)
        if experiment is None:
            return  # not queued: a duplicate job, or deleted
        try:
            variants = list(experiment.variants)
            work = [(i, case, v.id) for i, case in enumerate(experiment.cases or []) for v in variants]
            workers = max(1, min(experiment.concurrency or 1, MAX_CONCURRENCY, len(work)))
            if workers == 1:
                graph = build_graph(session, experiment, token, factory, retriever)
                by_id = {v.id: v for v in variants}
                for case_index, case, variant_id in work:
                    _invoke(graph, experiment, case_index, case, by_id[variant_id])
            else:
                session.commit()  # hold no transaction while the threads write
                _run_parallel(experiment_id, work, workers, token, session_factory, factory, retriever)
            status, error = "completed", None
        except _Superseded:
            logger.info("Experiment run superseded", extra={"experiment_id": experiment_id})
            return
        except Exception as exc:
            session.rollback()
            logger.exception("Experiment run failed", extra={"experiment_id": experiment_id})
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:1000]
        session.query(Experiment).filter(Experiment.id == experiment_id, Experiment.run_token == token).update(
            {Experiment.status: status, Experiment.error: error, Experiment.finished_at: _now()},
            synchronize_session=False,
        )
        session.commit()
    finally:
        session.close()
