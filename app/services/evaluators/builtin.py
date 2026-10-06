"""ragleitus's own LLM judge: one call that scores all four metrics."""

from __future__ import annotations

import json
import re

from app.services.evaluators.base import EvaluationInput, JudgeError, JudgeModel, Scores, clean_score
from app.services.llm import ChatMessage

NAME = "builtin"
LABEL = "Built-in judge"
DESCRIPTION = "One call to your judge model scores faithfulness, answer relevancy, context precision and recall."

JUDGE_SYSTEM = (
    "You are an impartial evaluator of answers produced by a retrieval-augmented assistant. "
    "Judge strictly from the material given. Reply with a single JSON object and nothing else."
)
JUDGE_INSTRUCTIONS = """Score the ANSWER on a scale from 0.0 to 1.0 for each metric:

- "faithfulness": the fraction of factual claims in the ANSWER that are supported by the CONTEXT passages. An answer that correctly says the context does not contain the information is fully faithful.
- "answer_relevancy": how directly and completely the ANSWER addresses the QUESTION.
- "context_precision": the fraction of CONTEXT passages that are relevant to the QUESTION.
- "context_recall": {recall_rule}

Return exactly: {{"faithfulness": number, "answer_relevancy": number, "context_precision": number, "context_recall": {recall_type}, "rationale": "one or two sentences"}}"""
RECALL_WITH_REFERENCE = "the fraction of facts in the REFERENCE ANSWER that can be found in the CONTEXT passages."
RECALL_WITHOUT_REFERENCE = "null (no reference answer was given)."


def installed() -> bool:
    return True


def build_judge_prompt(question: str, context: list[dict], answer: str, reference: str | None) -> list[ChatMessage]:
    passages = "\n\n".join(f"[{p['number']}] {p.get('content', p.get('snippet', ''))}" for p in context) or "(no passages)"
    parts = [
        # With a reference, ask for a number only: offered "number or null", small
        # models (ministral-8b) answered null although a reference was given.
        JUDGE_INSTRUCTIONS.format(
            recall_rule=RECALL_WITH_REFERENCE if reference else RECALL_WITHOUT_REFERENCE,
            recall_type="number" if reference else "null",
        ),
        f"QUESTION:\n{question}",
        f"CONTEXT:\n{passages}",
        f"ANSWER:\n{answer}",
    ]
    if reference:
        parts.append(f"REFERENCE ANSWER:\n{reference}")
    return [ChatMessage("system", JUDGE_SYSTEM), ChatMessage("user", "\n\n".join(parts))]


def parse_judge_output(text: str, has_reference: bool) -> Scores:
    """Read the judge's JSON, tolerating code fences or text around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise JudgeError("The judge model did not return JSON.")
    try:
        data = json.loads(match.group(0))
        scores = Scores(
            faithfulness=float(data["faithfulness"]),
            answer_relevancy=float(data["answer_relevancy"]),
            context_precision=float(data["context_precision"]),
            context_recall=data.get("context_recall"),
            rationale=str(data.get("rationale") or "")[:2000] or None,
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise JudgeError(f"The judge model returned malformed scores ({type(exc).__name__}).") from None
    return Scores(
        faithfulness=clean_score(scores.faithfulness),
        answer_relevancy=clean_score(scores.answer_relevancy),
        context_precision=clean_score(scores.context_precision),
        context_recall=clean_score(scores.context_recall) if has_reference else None,
        rationale=scores.rationale,
    )


async def evaluate(item: EvaluationInput, judge: JudgeModel, embedder=None) -> Scores:
    context = [{"number": i, "content": c} for i, c in enumerate(item.contexts, start=1)]
    text = await judge.complete(build_judge_prompt(item.question, context, item.answer, item.reference))
    return parse_judge_output(text, has_reference=bool(item.reference))
