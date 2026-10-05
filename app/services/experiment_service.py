"""Experiments: answer a set of questions with several variants and compare.

A variant is a prompt (the built-in one or a prompt-library version), a
provider and model, and a retrieval strategy with its top_k. Running an
experiment answers every question with every variant (see
experiment_runner, a LangGraph pipeline) and stores one result each: the
answer, its citations, latency, tokens, cost and, when the experiment asks
for it, the LLM judge's scores. `compare` averages them per variant;
`export` writes every result as CSV or JSON.

Legacy score-only experiments (Evaluation rows) are still summarised by
`summarize_experiments` for /api/evaluations/summary.
"""

from __future__ import annotations

import csv
import io
import logging
import statistics
import threading
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.document import Document
from app.models.experiment import Experiment, ExperimentResult, ExperimentVariant
from app.services.chat_service import ChatError
from app.services.evaluation_scoring import ScoreSummary, compare_experiments
from app.services.llm import UnknownProviderError, get_spec
from app.services.prompt_service import PromptNotFoundError, get_version
from app.services.provider_key import get_provider_key
from app.services.retrieval import STRATEGIES

logger = logging.getLogger(__name__)

MAX_CASES = 100
MAX_VARIANTS = 6
MAX_TOP_K = 20

# Metric -> whether higher is better.
JUDGE_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
METRICS = {
    "quality": True,  # mean of the judge metrics an answer has
    "faithfulness": True,
    "answer_relevancy": True,
    "context_precision": True,
    "context_recall": True,
    "hallucination": False,
    "rouge_l": True,
    "latency_ms": False,
    "cost_usd": False,
}
ACTIVE = ("queued", "running")


class ExperimentError(ChatError):
    status_code = 400


class ExperimentNotFoundError(ExperimentError):
    status_code = 404


class ExperimentBusyError(ExperimentError):
    status_code = 409


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes; they are stored as UTC.
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


# ---------------------------------------------------------------- create


def _clean_cases(cases: list[dict]) -> list[dict]:
    if not cases:
        raise ExperimentError("Add at least one question.")
    if len(cases) > MAX_CASES:
        raise ExperimentError(f"An experiment can have at most {MAX_CASES} questions.")
    cleaned = []
    for i, case in enumerate(cases, start=1):
        question = (case.get("question") or "").strip()
        if not question:
            raise ExperimentError(f"Question {i} is empty.")
        reference = (case.get("reference_answer") or "").strip() or None
        cleaned.append({"question": question[:4000], "reference_answer": reference[:20_000] if reference else None})
    return cleaned


def _check_provider(session: Session, user_id: int, provider: str, what: str):
    try:
        spec = get_spec(provider)
    except UnknownProviderError:
        raise ExperimentError(f"{what}: unknown provider '{provider}'.") from None
    if get_provider_key(session, user_id, provider) is None:
        raise ExperimentError(f"{what}: no API key stored for {spec.label}.")
    return spec


def _variant(session: Session, user_id: int, position: int, raw: dict) -> ExperimentVariant:
    label = (raw.get("label") or "").strip()[:100] or f"Variant {chr(ord('A') + position)}"
    spec = _check_provider(session, user_id, raw.get("provider") or "", label)
    model = (raw.get("model") or "").strip() or spec.default_model
    if not model:
        raise ExperimentError(f"{label}: choose a model.")
    retrieval = raw.get("retrieval") or "hybrid"
    if retrieval not in STRATEGIES:
        raise ExperimentError(f"{label}: retrieval must be one of {', '.join(STRATEGIES)}.")
    top_k = int(raw.get("top_k") or settings.retrieval_top_k)
    if not 1 <= top_k <= MAX_TOP_K:
        raise ExperimentError(f"{label}: top_k must be between 1 and {MAX_TOP_K}.")
    version_id = raw.get("prompt_version_id")
    if version_id:
        try:
            version = get_version(session, user_id, version_id)
        except PromptNotFoundError:
            raise ExperimentError(f"{label}: prompt version not found.") from None
        prompt_label = f"{version.prompt.name} v{version.version}"
    else:
        version_id, prompt_label = None, "Built-in prompt"
    return ExperimentVariant(
        position=position, label=label, prompt_version_id=version_id, prompt_label=prompt_label[:300],
        provider=spec.name, model=model[:255], retrieval=retrieval, top_k=top_k,
    )


def create_experiment(
    session: Session,
    user_id: int,
    name: str,
    cases: list[dict],
    variants: list[dict],
    document_ids: list[int] | None = None,
    evaluate: bool = True,
    judge_provider: str | None = None,
    judge_model: str | None = None,
) -> Experiment:
    name = (name or "").strip()
    if not name:
        raise ExperimentError("Give the experiment a name.")
    if not variants:
        raise ExperimentError("Add at least one variant.")
    if len(variants) > MAX_VARIANTS:
        raise ExperimentError(f"An experiment can have at most {MAX_VARIANTS} variants.")
    built = [_variant(session, user_id, i, raw) for i, raw in enumerate(variants)]
    if len({v.label for v in built}) != len(built):
        raise ExperimentError("Give each variant a different label.")
    if document_ids:
        owned = [
            doc_id for (doc_id,) in session.query(Document.id).filter(Document.user_id == user_id, Document.id.in_(document_ids))
        ]
        if len(owned) != len(set(document_ids)):
            raise ExperimentError("Some of the chosen documents were not found.")
        document_ids = sorted(owned)
    if judge_provider:
        _check_provider(session, user_id, judge_provider, "Judge")
    experiment = Experiment(
        user_id=user_id,
        name=name[:255],
        status="draft",
        cases=_clean_cases(cases),
        document_ids=document_ids or None,
        evaluate=bool(evaluate),
        judge_provider=judge_provider or None,
        judge_model=(judge_model or "").strip() or None,
        created_at=_now(),
        variants=built,
    )
    session.add(experiment)
    session.flush()
    return experiment


# ---------------------------------------------------------------- read


def get_experiment(session: Session, user_id: int, experiment_id: int) -> Experiment:
    experiment = (
        session.query(Experiment)
        .options(selectinload(Experiment.variants))
        .filter(Experiment.id == experiment_id, Experiment.user_id == user_id, Experiment.cases.isnot(None))
        .first()
    )
    if experiment is None:
        raise ExperimentNotFoundError("Experiment not found")
    return experiment


def list_experiments(session: Session, user_id: int) -> list[Experiment]:
    """The user's experiments, newest first (legacy score-only ones are left out)."""
    return (
        session.query(Experiment)
        .options(selectinload(Experiment.variants))
        .filter(Experiment.user_id == user_id, Experiment.cases.isnot(None))
        .order_by(Experiment.id.desc())
        .all()
    )


def _done_counts(session: Session, experiment_ids: list[int]) -> dict[int, int]:
    if not experiment_ids:
        return {}
    rows = (
        session.query(ExperimentResult.experiment_id, func.count())
        .filter(ExperimentResult.experiment_id.in_(experiment_ids))
        .group_by(ExperimentResult.experiment_id)
        .all()
    )
    return dict(rows)


def variant_dict(variant: ExperimentVariant) -> dict:
    return {
        "id": variant.id,
        "label": variant.label,
        "prompt_version_id": variant.prompt_version_id,
        "prompt_label": variant.prompt_label,
        "provider": variant.provider,
        "model": variant.model,
        "retrieval": variant.retrieval,
        "top_k": variant.top_k,
    }


def experiment_dict(experiment: Experiment, done: int, with_cases: bool = False) -> dict:
    total = len(experiment.cases or []) * len(experiment.variants)
    data = {
        "id": experiment.id,
        "name": experiment.name,
        "status": experiment.status,
        "error": experiment.error,
        "created_at": experiment.created_at,
        "started_at": experiment.started_at,
        "finished_at": experiment.finished_at,
        "case_count": len(experiment.cases or []),
        "variants": [variant_dict(v) for v in experiment.variants],
        "document_ids": experiment.document_ids,
        "evaluate": experiment.evaluate,
        "judge_provider": experiment.judge_provider,
        "judge_model": experiment.judge_model,
        "progress": {"done": done, "total": total},
    }
    if with_cases:
        data["cases"] = experiment.cases
    return data


def describe(session: Session, experiment: Experiment, with_cases: bool = True) -> dict:
    return experiment_dict(experiment, _done_counts(session, [experiment.id]).get(experiment.id, 0), with_cases)


def describe_all(session: Session, user_id: int) -> list[dict]:
    experiments = list_experiments(session, user_id)
    done = _done_counts(session, [e.id for e in experiments])
    return [experiment_dict(e, done.get(e.id, 0)) for e in experiments]


def delete_experiment(session: Session, user_id: int, experiment_id: int) -> None:
    session.delete(get_experiment(session, user_id, experiment_id))
    session.flush()


# ---------------------------------------------------------------- run


def is_stale(experiment: Experiment, now: datetime | None = None) -> bool:
    """A queued or running experiment whose run was lost (worker crash, restart)."""
    started = _aware(experiment.started_at)
    cutoff = (now or _now()) - timedelta(minutes=settings.index_stale_minutes)
    return experiment.status in ACTIVE and (started is None or started < cutoff)


def start_run(session: Session, user_id: int, experiment_id: int) -> Experiment:
    """Queue a (re-)run: earlier results are discarded."""
    experiment = get_experiment(session, user_id, experiment_id)
    if experiment.status in ACTIVE and not is_stale(experiment):
        raise ExperimentBusyError("The experiment is already running.")
    for variant in experiment.variants:
        _check_provider(session, user_id, variant.provider, variant.label)
    if experiment.judge_provider:
        _check_provider(session, user_id, experiment.judge_provider, "Judge")
    session.query(ExperimentResult).filter(ExperimentResult.experiment_id == experiment.id).delete(synchronize_session=False)
    experiment.status = "queued"
    experiment.error = None
    experiment.run_token = None
    # When the run was requested; the runner sets it again when it starts.
    experiment.started_at = _now()
    experiment.finished_at = None
    session.flush()
    return experiment


def schedule_run(experiment_id: int, background_tasks: BackgroundTasks | None = None, factory=None) -> None:
    """Run the experiment in a worker (TASK_QUEUE=celery) or in this process
    after the response, like document indexing. Call after committing.

    `factory` replaces how providers are built for an in-process run (tests).
    """
    if settings.task_queue == "celery":
        from app.worker import run_experiment_task  # imported here: the worker imports the runner

        try:
            run_experiment_task.delay(experiment_id)
        except Exception:
            logger.exception("Could not queue the experiment", extra={"experiment_id": experiment_id})
        return
    from app.services.experiment_runner import run_experiment

    kwargs = {"factory": factory} if factory is not None else {}
    if background_tasks is not None:
        background_tasks.add_task(run_experiment, experiment_id, **kwargs)
    else:
        threading.Thread(target=run_experiment, args=(experiment_id,), kwargs=kwargs, name="experiment", daemon=True).start()


# ---------------------------------------------------------------- compare and export


def _results(session: Session, experiment: Experiment) -> list[ExperimentResult]:
    return (
        session.query(ExperimentResult)
        .filter(ExperimentResult.experiment_id == experiment.id)
        .order_by(ExperimentResult.case_index, ExperimentResult.variant_id)
        .all()
    )


def _quality(result: ExperimentResult) -> float | None:
    scores = [getattr(result, m) for m in JUDGE_METRICS if getattr(result, m) is not None]
    return round(statistics.fmean(scores), 4) if scores else None


def _metric(result: ExperimentResult, metric: str) -> float | None:
    return _quality(result) if metric == "quality" else getattr(result, metric)


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(statistics.fmean(present), 6) if present else None


def compare(session: Session, user_id: int, experiment_id: int) -> dict:
    """Per-variant averages, the best variant per metric, and every answer by question."""
    experiment = get_experiment(session, user_id, experiment_id)
    results = _results(session, experiment)
    by_variant: dict[int, list[ExperimentResult]] = {v.id: [] for v in experiment.variants}
    for r in results:
        by_variant.setdefault(r.variant_id, []).append(r)

    variants = []
    for variant in experiment.variants:
        rows = by_variant[variant.id]
        answered = [r for r in rows if r.answer is not None]
        costs = [r.cost_usd for r in answered if r.cost_usd is not None]
        variants.append(
            {
                **variant_dict(variant),
                "results": len(rows),
                "errors": sum(1 for r in rows if r.error),
                "averages": {metric: _mean([_metric(r, metric) for r in answered]) for metric in METRICS},
                "total_cost_usd": round(sum(costs), 8) if costs else None,
                "prompt_tokens": sum(r.prompt_tokens or 0 for r in answered),
                "completion_tokens": sum(r.completion_tokens or 0 for r in answered),
            }
        )

    # A variant is best at a metric only if it is strictly ahead of every
    # other; a tie for first names none.
    best = {}
    for metric, higher in METRICS.items():
        scored = sorted(
            ((v["averages"][metric], v["id"]) for v in variants if v["averages"][metric] is not None),
            key=lambda item: item[0],
            reverse=higher,
        )
        if len(scored) > 1 and scored[0][0] != scored[1][0]:
            best[metric] = scored[0][1]

    cases = []
    for index, case in enumerate(experiment.cases or []):
        answers = {}
        for r in results:
            if r.case_index == index:
                answers[r.variant_id] = {
                    "answer": r.answer,
                    "citations": r.citations or [],
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                    "cost_usd": r.cost_usd,
                    "quality": _quality(r),
                    **{m: getattr(r, m) for m in (*JUDGE_METRICS, "hallucination", "rouge_l")},
                    "judge_rationale": r.judge_rationale,
                }
        cases.append({"index": index, **case, "results": answers})

    return {"experiment": describe(session, experiment, with_cases=False), "variants": variants, "best": best, "cases": cases}


EXPORT_COLUMNS = [
    "experiment", "case", "question", "reference_answer", "variant", "prompt", "provider", "model", "retrieval",
    "top_k", "answer", "cited_passages", "quality", *JUDGE_METRICS, "hallucination", "rouge_l", "latency_ms",
    "prompt_tokens", "completion_tokens", "cost_usd", "error",
]


def export_rows(session: Session, user_id: int, experiment_id: int) -> tuple[Experiment, list[dict]]:
    experiment = get_experiment(session, user_id, experiment_id)
    variants = {v.id: v for v in experiment.variants}
    rows = []
    for r in _results(session, experiment):
        variant = variants[r.variant_id]
        case = (experiment.cases or [])[r.case_index]
        rows.append(
            {
                "experiment": experiment.name,
                "case": r.case_index + 1,
                "question": case["question"],
                "reference_answer": case.get("reference_answer"),
                "variant": variant.label,
                "prompt": variant.prompt_label,
                "provider": variant.provider,
                "model": variant.model,
                "retrieval": variant.retrieval,
                "top_k": variant.top_k,
                "answer": r.answer,
                "cited_passages": " ".join(f"[{c['number']}]" for c in (r.citations or [])),
                "quality": _quality(r),
                **{m: getattr(r, m) for m in (*JUDGE_METRICS, "hallucination", "rouge_l", "latency_ms",
                                              "prompt_tokens", "completion_tokens", "cost_usd", "error")},
            }
        )
    return experiment, rows


def _spreadsheet_safe(value):
    # A cell starting with one of these is run as a formula by spreadsheet apps.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_csv(session: Session, user_id: int, experiment_id: int) -> tuple[Experiment, str]:
    experiment, rows = export_rows(session, user_id, experiment_id)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _spreadsheet_safe(v) for k, v in row.items()})
    return experiment, buffer.getvalue()


def export_json(session: Session, user_id: int, experiment_id: int) -> tuple[Experiment, dict]:
    experiment, rows = export_rows(session, user_id, experiment_id)
    return experiment, {"experiment": describe(session, experiment), "results": rows}


# ---------------------------------------------------------------- report


def report(session: Session, user_id: int) -> dict:
    """Every experiment with its best variant per metric; and the variant with
    the best answer quality in the most recent experiment that has a clear one."""
    entries = []
    best_performing = None
    for data in describe_all(session, user_id):
        best = {}
        if data["status"] == "completed":
            comparison = compare(session, user_id, data["id"])
            labels = {v["id"]: v["label"] for v in comparison["variants"]}
            best = {metric: labels[variant_id] for metric, variant_id in comparison["best"].items()}
            winner = comparison["best"].get("quality")
            if best_performing is None and winner is not None:
                variant = next(v for v in comparison["variants"] if v["id"] == winner)
                best_performing = {
                    "experiment_id": data["id"],
                    "experiment": data["name"],
                    "variant": variant["label"],
                    "quality": variant["averages"]["quality"],
                }
        entries.append({**data, "best": best})
    return {
        "experiments_evaluated": sum(1 for e in entries if e["status"] == "completed"),
        "best_performing": best_performing,
        "experiments": entries,
    }


# ---------------------------------------------------------------- legacy


def summarize_experiments(session: Session, user_id: int) -> dict[str, ScoreSummary]:
    """Side-by-side score summaries of the user's own legacy experiments, keyed by name."""
    experiments = (
        session.query(Experiment)
        .options(selectinload(Experiment.evaluations))
        .filter(Experiment.user_id == user_id)
        .order_by(Experiment.id)
        .all()
    )
    scores: dict[str, list[float | None]] = {}
    for exp in experiments:
        if not exp.evaluations and exp.cases is not None:
            continue  # a new-style experiment: compared through /api/experiments instead
        # Names are not unique; keep each experiment rather than letting a later one replace an earlier one.
        name = exp.name if exp.name not in scores else f"{exp.name} (#{exp.id})"
        scores[name] = [e.score for e in exp.evaluations]
    return compare_experiments(scores)
