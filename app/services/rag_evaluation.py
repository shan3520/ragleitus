"""Evaluating chat answers: an evaluator's scores, judged by the user's model.

For one assistant message the evaluator sees the question, the passages the
answer was given, the answer, and optionally a reference answer, and scores:

- faithfulness: share of the answer's claims supported by the passages
- answer_relevancy: how directly and completely it answers the question
- context_precision: share of the passages that are relevant to the question
- context_recall: share of the reference answer's facts found in the passages
  (only with a reference answer)

The evaluator is RAGForge's own LLM judge (one call), Ragas or DeepEval (see
app.services.evaluators); all run on the user's own provider key, and every
call they make is recorded in telemetry. Hallucination is 1 - faithfulness
(DeepEval measures it directly). Two lexical baselines that need no model
are stored alongside for comparison.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session, load_only, selectinload

from app.models.answer_evaluation import AnswerEvaluation
from app.models.conversation import Conversation, Message
from app.services import embedding_service, evaluators, telemetry
from app.services.chat_service import ProviderChoiceError
from app.services.embeddings import Embedder
from app.services.evaluators import EvaluationError, EvaluationInput, JudgeError, JudgeModel, Scores
from app.services.evaluators.base import JUDGE_MAX_TOKENS
from app.services.evaluators.builtin import (  # noqa: F401  (part of this module's interface)
    JUDGE_INSTRUCTIONS,
    JUDGE_SYSTEM,
    RECALL_WITH_REFERENCE,
    RECALL_WITHOUT_REFERENCE,
    build_judge_prompt,
    parse_judge_output,
)
from app.services.jaccard_scoring import score_jaccard
from app.services.llm import ProviderFactory, create_provider, get_spec
from app.services.provider_key import MissingProviderKeyError, create_user_provider
from app.services.rouge_scoring import score_rouge_l


class MessageNotFoundError(EvaluationError):
    status_code = 404


def _load_answer(session: Session, user_id: int, message_id: int) -> tuple[Message, str]:
    message = (
        session.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Message.id == message_id, Conversation.user_id == user_id)
        .first()
    )
    if message is None:
        raise MessageNotFoundError("Message not found")
    if message.role != "assistant":
        raise EvaluationError("Only assistant answers can be evaluated.")
    question = (
        session.query(Message.content)
        .filter(Message.conversation_id == message.conversation_id, Message.role == "user", Message.id < message.id)
        .order_by(Message.id.desc())
        .limit(1)
        .scalar()
    )
    return message, question or ""


def resolve_judge(session: Session, user_id: int, provider: str, model: str | None, factory: ProviderFactory) -> JudgeModel:
    """The user's judge: their provider (with their key) and the model, or the provider's default."""
    try:
        spec = get_spec(provider)
    except ValueError:
        raise ProviderChoiceError(f"Unknown provider '{provider}'")
    model = model or spec.default_model
    if not model:
        raise ProviderChoiceError(f"Provider '{provider}' has no default model; pass a model name.")
    try:
        adapter = create_user_provider(session, user_id, provider, factory)
    except MissingProviderKeyError:
        raise ProviderChoiceError(f"No API key stored for provider '{provider}'.")
    return JudgeModel(provider, adapter, model, JUDGE_MAX_TOKENS)


def user_embedder(session: Session, user_id: int) -> Embedder:
    """The embedding model Ragas's answer relevancy uses: the user's own choice."""
    try:
        return embedding_service.build_embedder(session, user_id, embedding_service.get_choice(session, user_id))
    except embedding_service.EmbeddingUnavailable as exc:
        raise EvaluationError(str(exc)) from None


def record_judge_calls(session: Session, user_id: int, judge: JudgeModel, conversation_id=None, message_id=None) -> None:
    """Telemetry for every call the evaluator made through the judge."""
    for call in judge.calls:
        telemetry.record_llm_call(
            session, user_id=user_id, operation="evaluation", provider=judge.provider_name, model=call.model,
            latency_ms=call.latency_ms, usage=call.usage, prompt_text=call.prompt_text,
            completion_text=call.completion_text, error=call.error,
            conversation_id=conversation_id, message_id=message_id,
        )
    judge.calls.clear()


async def score(item: EvaluationInput, judge: JudgeModel, evaluator: str | None, embedder: Embedder | None) -> Scores:
    """Run an evaluator; an evaluator library's own failure is reported as a judge error."""
    module = evaluators.get(evaluator)
    try:
        return await module.evaluate(item, judge, embedder)
    except EvaluationError:
        raise
    except Exception as exc:  # the libraries raise their own exception types
        raise JudgeError(f"{module.LABEL} could not score the answer ({type(exc).__name__}: {str(exc)[:200]}).") from None


@dataclass
class _Prepared:
    message: Message
    question: str
    judge: JudgeModel
    embedder: Embedder | None


def _prepare(session, user_id, message_id, provider, model, factory, evaluator) -> _Prepared:
    evaluators.get(evaluator)  # unknown or not installed: refuse before any call
    message, question = _load_answer(session, user_id, message_id)
    judge_provider = provider or message.provider
    if not judge_provider:
        raise ProviderChoiceError("Choose a judge provider.")
    judge_model = model or (message.model if judge_provider == message.provider else None)
    judge = resolve_judge(session, user_id, judge_provider, judge_model, factory)
    embedder = user_embedder(session, user_id) if evaluator == "ragas" else None
    return _Prepared(message, question, judge, embedder)


def _record_failure(session: Session, user_id: int, prepared: _Prepared) -> None:
    record_judge_calls(session, user_id, prepared.judge, prepared.message.conversation_id, prepared.message.id)
    embedding_service.record_calls(session, user_id, prepared.embedder)
    session.commit()


def _store_evaluation(session, user_id, prepared: _Prepared, scores: Scores, reference, evaluator) -> AnswerEvaluation:
    message = prepared.message
    record_judge_calls(session, user_id, prepared.judge, message.conversation_id, message.id)
    embedding_service.record_calls(session, user_id, prepared.embedder)
    context_text = " ".join(p.get("content", "") for p in message.context or [])
    evaluation = AnswerEvaluation(
        user_id=user_id,
        message_id=message.id,
        evaluator=evaluators.get(evaluator).NAME,
        judge_provider=prepared.judge.provider_name,
        judge_model=prepared.judge.model,
        faithfulness=scores.faithfulness,
        answer_relevancy=scores.answer_relevancy,
        context_precision=scores.context_precision,
        context_recall=scores.context_recall if reference else None,
        hallucination=scores.hallucination_score(),
        rationale=scores.rationale,
        reference_answer=reference,
        rouge_l=score_rouge_l(message.content, reference) if reference else None,
        context_overlap=round(score_jaccard(message.content, context_text), 4) if context_text else None,
    )
    session.add(evaluation)
    session.flush()
    return evaluation


async def evaluate_message(
    session: Session,
    user_id: int,
    message_id: int,
    reference: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    factory: ProviderFactory = create_provider,
    evaluator: str | None = None,
) -> AnswerEvaluation:
    # Database work runs in a worker thread (one step at a time, so the session
    # is never used concurrently); only the provider calls run on the event loop.
    prepared = await asyncio.to_thread(_prepare, session, user_id, message_id, provider, model, factory, evaluator)
    message = prepared.message
    item = EvaluationInput(
        question=prepared.question,
        answer=message.content,
        contexts=[p.get("content", "") for p in message.context or []],
        reference=reference,
    )
    try:
        scores = await score(item, prepared.judge, evaluator, prepared.embedder)
    except EvaluationError:
        await asyncio.to_thread(_record_failure, session, user_id, prepared)
        raise
    return await asyncio.to_thread(_store_evaluation, session, user_id, prepared, scores, reference, evaluator)


METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall", "hallucination")


def list_evaluations(session: Session, user_id: int, limit: int = 50, offset: int = 0, conversation_id: int | None = None):
    query = session.query(AnswerEvaluation).filter(AnswerEvaluation.user_id == user_id)
    if conversation_id is not None:
        query = query.join(Message, AnswerEvaluation.message_id == Message.id).filter(Message.conversation_id == conversation_id)
    total = query.count()
    averages_row = query.with_entities(*[func.avg(getattr(AnswerEvaluation, m)) for m in METRICS]).one()
    averages = {m: (round(v, 4) if v is not None else None) for m, v in zip(METRICS, averages_row)}
    items = (
        # conversation_id without a query per row, and without loading each answer's text and context.
        query.options(selectinload(AnswerEvaluation.message).options(load_only(Message.id, Message.conversation_id)))
        .order_by(AnswerEvaluation.created_at.desc(), AnswerEvaluation.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return items, total, averages
