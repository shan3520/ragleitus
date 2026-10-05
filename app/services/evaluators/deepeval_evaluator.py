"""DeepEval metrics, judged by the user's own provider and model.

FaithfulnessMetric, AnswerRelevancyMetric, ContextualPrecisionMetric (with
a reference answer; ContextualRelevancyMetric without one, as the context
precision score), ContextualRecallMetric (reference only) and
HallucinationMetric (against the retrieved passages; stored as the share of
passages the answer contradicts, as our other evaluators report it). DeepEval's own model
clients are not used: a DeepEvalBaseLLM adapter routes its calls through our
provider adapters, so the user's key, provider and telemetry apply. Metrics
run in plain LLM mode; nothing is sent to Confident AI.

Optional: `pip install ".[deepeval]"`. DeepEval's telemetry is switched off.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache

from app.services.evaluators._sync import run_sync
from app.services.evaluators.base import EvaluationInput, EvaluatorUnavailable, JudgeModel, Scores, clean_score
from app.services.llm import ChatMessage

NAME = "deepeval"
LABEL = "DeepEval"
DESCRIPTION = (
    "DeepEval faithfulness, answer relevancy, contextual precision/relevancy, contextual recall "
    "and hallucination; several calls per answer."
)
NO_PASSAGES = "(No passages were retrieved.)"

# Before DeepEval is imported: no telemetry, no update checks.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_UPDATE_WARNING_OPT_IN", "NO")


def installed() -> bool:
    return importlib.util.find_spec("deepeval") is not None


@lru_cache(maxsize=1)
def _adapter():
    from deepeval.models import DeepEvalBaseLLM

    class ProviderDeepEvalLLM(DeepEvalBaseLLM):
        def __init__(self, judge: JudgeModel):
            self.judge = judge
            super().__init__(model=f"{judge.provider_name}/{judge.model}")

        def load_model(self):
            return self

        async def a_generate(self, prompt: str, schema=None):
            if schema is not None:
                return await self.judge.complete_json(prompt, schema)
            return await self.judge.complete([ChatMessage("user", prompt)])

        def generate(self, prompt: str, schema=None):
            return run_sync(self.a_generate(prompt, schema))

        def get_model_name(self):
            return f"{self.judge.provider_name}/{self.judge.model}"

    return ProviderDeepEvalLLM


async def evaluate(item: EvaluationInput, judge: JudgeModel, embedder=None) -> Scores:
    if not installed():
        raise EvaluatorUnavailable('DeepEval is not installed on this server (pip install ".[deepeval]").')
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
        HallucinationMetric,
    )
    from deepeval.test_case import LLMTestCase

    model = _adapter()(judge)
    contexts = item.contexts or [NO_PASSAGES]
    case = LLMTestCase(
        input=item.question,
        actual_output=item.answer,
        expected_output=item.reference,
        retrieval_context=contexts,
        context=contexts,
    )
    options = {"model": model, "eval_mode": "llm", "async_mode": True, "include_reason": True}

    async def measure(metric):
        await metric.a_measure(case, _show_indicator=False)
        return metric

    faithfulness = await measure(FaithfulnessMetric(**options))
    relevancy = await measure(AnswerRelevancyMetric(**options))
    precision = await measure(
        ContextualPrecisionMetric(**options) if item.reference else ContextualRelevancyMetric(**options)
    )
    recall = await measure(ContextualRecallMetric(**options)) if item.reference else None
    hallucination = await measure(HallucinationMetric(**options))

    reasons = [f"{label}: {m.reason}" for label, m in (("Faithfulness", faithfulness), ("Relevancy", relevancy)) if m.reason]
    return Scores(
        faithfulness=clean_score(faithfulness.score),
        answer_relevancy=clean_score(relevancy.score),
        context_precision=clean_score(precision.score),
        context_recall=clean_score(recall.score) if recall is not None else None,
        # DeepEval 4's HallucinationMetric scores agreement with the passages
        # (higher is better); our hallucination is the share that disagrees.
        hallucination=clean_score(1 - hallucination.score) if hallucination.score is not None else None,
        rationale=" ".join(reasons)[:2000] or "Scored with DeepEval.",
    )
