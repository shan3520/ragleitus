"""What every evaluator shares: its input, its scores, and the judge model.

The judge is the user's own provider and model (through our adapters, with
their key). It keeps a log of its calls so the caller can record them in
telemetry, and `complete_json` turns its replies into the structured objects
Ragas and DeepEval ask for, retrying when the reply is not valid JSON.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.services.chat_service import ChatError
from app.services.llm import ChatMessage, ChatProvider, ProviderError, Usage, complete

JUDGE_MAX_TOKENS = 4000
JSON_RETRIES = 2


class EvaluationError(ChatError):
    status_code = 400


class JudgeError(EvaluationError):
    """The judge model failed or answered in a form that can't be read."""

    status_code = 502


class EvaluatorUnavailable(EvaluationError):
    """The evaluator's library is not installed on this server."""


@dataclass(frozen=True)
class EvaluationInput:
    question: str
    answer: str
    contexts: list[str]
    reference: str | None = None


@dataclass(frozen=True)
class Scores:
    """0..1 each. A metric the evaluator could not score is None (Ragas
    reports no faithfulness for an answer without claims, for example)."""

    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None
    rationale: str | None = None
    # When the evaluator measures it directly (DeepEval); otherwise 1 - faithfulness.
    hallucination: float | None = None

    def hallucination_score(self) -> float | None:
        if self.hallucination is not None:
            return self.hallucination
        return round(1.0 - self.faithfulness, 4) if self.faithfulness is not None else None


def clean_score(value) -> float | None:
    """A 0..1 score, or None for a missing or NaN value."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return round(max(0.0, min(1.0, number)), 4)


@dataclass(frozen=True)
class JudgeCall:
    latency_ms: float
    usage: Usage
    prompt_text: str
    completion_text: str
    model: str
    error: ProviderError | None = None


SchemaT = TypeVar("SchemaT", bound=BaseModel)

_JSON_SYSTEM = (
    "You are an evaluation assistant. Reply with one JSON object that matches this JSON schema, "
    "and nothing else:\n{schema}"
)


@dataclass
class JudgeModel:
    """The judge LLM: a provider adapter and a model, logging every call."""

    provider_name: str
    provider: ChatProvider
    model: str
    max_tokens: int = JUDGE_MAX_TOKENS
    calls: list[JudgeCall] = field(default_factory=list)

    async def complete(self, messages: list[ChatMessage]) -> str:
        prompt_text = "\n\n".join(m.content for m in messages)
        started = time.perf_counter()
        try:
            result = await complete(self.provider, messages, self.model, self.max_tokens)
        except ProviderError as exc:
            self.calls.append(JudgeCall((time.perf_counter() - started) * 1000, Usage(), prompt_text, "", self.model, exc))
            raise JudgeError(exc.message) from None
        self.calls.append(
            JudgeCall((time.perf_counter() - started) * 1000, result.usage, prompt_text, result.text, result.model or self.model)
        )
        return result.text

    async def complete_json(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        """Ask for a JSON object matching `schema`; retry with the error if the reply doesn't fit."""
        messages = [
            ChatMessage("system", _JSON_SYSTEM.format(schema=json.dumps(schema.model_json_schema()))),
            ChatMessage("user", prompt),
        ]
        for attempt in range(JSON_RETRIES + 1):
            text = await self.complete(messages)
            try:
                return schema.model_validate_json(extract_json(text))
            except (ValueError, ValidationError) as exc:
                if attempt == JSON_RETRIES:
                    raise JudgeError(f"The judge model did not return the expected JSON ({type(exc).__name__}).") from None
                messages = [
                    *messages,
                    ChatMessage("assistant", text),
                    ChatMessage("user", f"That was not valid JSON for the schema ({str(exc)[:300]}). Reply with the JSON object only."),
                ]
        raise AssertionError("unreachable")


def extract_json(text: str) -> str:
    """The JSON object in a reply, without code fences or text around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the reply")
    return match.group(0)
