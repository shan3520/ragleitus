"""Evaluating chat answers with an LLM judge (LLM-as-a-judge).

For one assistant message the judge sees the question, the passages the
answer was given, the answer, and optionally a reference answer, and scores:

- faithfulness: share of the answer's claims supported by the passages
- answer_relevancy: how directly and completely it answers the question
- context_precision: share of the passages that are relevant to the question
- context_recall: share of the reference answer's facts found in the passages
  (only with a reference answer)

Hallucination is reported as 1 - faithfulness. Two lexical baselines that
need no model are stored alongside for comparison. The judge runs on the
user's own provider key and is recorded in telemetry like any other call.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.answer_evaluation import AnswerEvaluation
from app.models.conversation import Conversation, Message
from app.services import telemetry
from app.services.chat_service import ChatError, ProviderChoiceError
from app.services.jaccard_scoring import score_jaccard
from app.services.llm import ChatMessage, ProviderError, ProviderFactory, complete, create_provider, get_spec
from app.services.provider_key import MissingProviderKeyError, create_user_provider
from app.services.rouge_scoring import score_rouge_l

JUDGE_MAX_TOKENS = 4000
JUDGE_SYSTEM = (
    "You are an impartial evaluator of answers produced by a retrieval-augmented assistant. "
    "Judge strictly from the material given. Reply with a single JSON object and nothing else."
)
JUDGE_INSTRUCTIONS = """Score the ANSWER on a scale from 0.0 to 1.0 for each metric:

- "faithfulness": the fraction of factual claims in the ANSWER that are supported by the CONTEXT passages. An answer that correctly says the context does not contain the information is fully faithful.
- "answer_relevancy": how directly and completely the ANSWER addresses the QUESTION.
- "context_precision": the fraction of CONTEXT passages that are relevant to the QUESTION.
- "context_recall": {recall_rule}

Return exactly: {{"faithfulness": number, "answer_relevancy": number, "context_precision": number, "context_recall": number or null, "rationale": "one or two sentences"}}"""
RECALL_WITH_REFERENCE = "the fraction of facts in the REFERENCE ANSWER that can be found in the CONTEXT passages."
RECALL_WITHOUT_REFERENCE = "null (no reference answer was given)."


class EvaluationError(ChatError):
    status_code = 400


class MessageNotFoundError(EvaluationError):
    status_code = 404


class JudgeError(EvaluationError):
    status_code = 502


@dataclass(frozen=True)
class JudgeScores:
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float | None
    rationale: str | None


def _clamp(value) -> float:
    return max(0.0, min(1.0, float(value)))


def parse_judge_output(text: str, has_reference: bool) -> JudgeScores:
    """Read the judge's JSON, tolerating code fences or text around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise JudgeError("The judge model did not return JSON.")
    try:
        data = json.loads(match.group(0))
        recall = data.get("context_recall")
        return JudgeScores(
            faithfulness=_clamp(data["faithfulness"]),
            answer_relevancy=_clamp(data["answer_relevancy"]),
            context_precision=_clamp(data["context_precision"]),
            context_recall=_clamp(recall) if has_reference and recall is not None else None,
            rationale=str(data.get("rationale") or "")[:2000] or None,
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise JudgeError(f"The judge model returned malformed scores ({type(exc).__name__}).") from None


def build_judge_prompt(question: str, context: list[dict], answer: str, reference: str | None) -> list[ChatMessage]:
    passages = "\n\n".join(f"[{p['number']}] {p.get('content', p.get('snippet', ''))}" for p in context) or "(no passages)"
    parts = [
        JUDGE_INSTRUCTIONS.format(recall_rule=RECALL_WITH_REFERENCE if reference else RECALL_WITHOUT_REFERENCE),
        f"QUESTION:\n{question}",
        f"CONTEXT:\n{passages}",
        f"ANSWER:\n{answer}",
    ]
    if reference:
        parts.append(f"REFERENCE ANSWER:\n{reference}")
    return [ChatMessage("system", JUDGE_SYSTEM), ChatMessage("user", "\n\n".join(parts))]


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


@dataclass
class _JudgeCall:
    message: Message
    judge_provider: str
    judge_model: str
    judge: object
    prompt: list
    prompt_text: str
    context: list


def _prepare_judge(session, user_id, message_id, reference, provider, model, factory) -> _JudgeCall:
    message, question = _load_answer(session, user_id, message_id)
    judge_provider = provider or message.provider
    if not judge_provider:
        raise ProviderChoiceError("Choose a judge provider.")
    try:
        spec = get_spec(judge_provider)
    except ValueError:
        raise ProviderChoiceError(f"Unknown provider '{judge_provider}'")
    judge_model = model or (message.model if judge_provider == message.provider else None) or spec.default_model
    if not judge_model:
        raise ProviderChoiceError(f"Provider '{judge_provider}' has no default model; pass a model name.")
    try:
        judge = create_user_provider(session, user_id, judge_provider, factory)
    except MissingProviderKeyError:
        raise ProviderChoiceError(f"No API key stored for provider '{judge_provider}'.")

    context = message.context or []
    prompt = build_judge_prompt(question, context, message.content, reference)
    prompt_text = "\n\n".join(m.content for m in prompt)
    return _JudgeCall(message, judge_provider, judge_model, judge, prompt, prompt_text, context)


def _record_judge_failure(session: Session, user_id: int, call: _JudgeCall, latency_ms: float, exc: ProviderError) -> None:
    telemetry.record_llm_call(
        session, user_id=user_id, operation="evaluation", provider=call.judge_provider, model=call.judge_model,
        latency_ms=latency_ms, error=exc, prompt_text=call.prompt_text,
        conversation_id=call.message.conversation_id, message_id=call.message.id,
    )
    session.commit()


def _store_evaluation(session: Session, user_id: int, call: _JudgeCall, result, latency_ms: float, reference: str | None) -> AnswerEvaluation:
    message = call.message
    telemetry.record_llm_call(
        session, user_id=user_id, operation="evaluation", provider=call.judge_provider, model=result.model or call.judge_model,
        latency_ms=latency_ms, usage=result.usage, prompt_text=call.prompt_text,
        completion_text=result.text, conversation_id=message.conversation_id, message_id=message.id,
    )
    session.commit()
    scores = parse_judge_output(result.text, has_reference=bool(reference))

    context_text = " ".join(p.get("content", "") for p in call.context)
    evaluation = AnswerEvaluation(
        user_id=user_id,
        message_id=message.id,
        judge_provider=call.judge_provider,
        judge_model=call.judge_model,
        faithfulness=scores.faithfulness,
        answer_relevancy=scores.answer_relevancy,
        context_precision=scores.context_precision,
        context_recall=scores.context_recall,
        hallucination=round(1.0 - scores.faithfulness, 4),
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
) -> AnswerEvaluation:
    # Database work runs in a worker thread (one step at a time, so the session
    # is never used concurrently); only the provider call runs on the event loop.
    call = await asyncio.to_thread(_prepare_judge, session, user_id, message_id, reference, provider, model, factory)
    started = time.perf_counter()
    try:
        result = await complete(call.judge, call.prompt, call.judge_model, JUDGE_MAX_TOKENS)
    except ProviderError as exc:
        await asyncio.to_thread(_record_judge_failure, session, user_id, call, (time.perf_counter() - started) * 1000, exc)
        raise JudgeError(exc.message) from None
    latency_ms = (time.perf_counter() - started) * 1000
    return await asyncio.to_thread(_store_evaluation, session, user_id, call, result, latency_ms, reference)


METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall", "hallucination")


def list_evaluations(session: Session, user_id: int, limit: int = 50, offset: int = 0, conversation_id: int | None = None):
    query = session.query(AnswerEvaluation).filter(AnswerEvaluation.user_id == user_id)
    if conversation_id is not None:
        query = query.join(Message, AnswerEvaluation.message_id == Message.id).filter(Message.conversation_id == conversation_id)
    total = query.count()
    averages_row = query.with_entities(*[func.avg(getattr(AnswerEvaluation, m)) for m in METRICS]).one()
    averages = {m: (round(v, 4) if v is not None else None) for m, v in zip(METRICS, averages_row)}
    items = query.order_by(AnswerEvaluation.created_at.desc(), AnswerEvaluation.id.desc()).offset(offset).limit(limit).all()
    return items, total, averages
