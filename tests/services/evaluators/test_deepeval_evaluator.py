import asyncio

import pytest

from app.services.evaluators import EvaluationInput, JudgeModel, deepeval_evaluator
from tests.fakes import SchemaJudgeProvider

pytestmark = pytest.mark.skipif(not deepeval_evaluator.installed(), reason="deepeval is not installed (pip install \".[deepeval]\")")

ITEM = EvaluationInput(
    question="What does error E-4711 mean?",
    answer="Error E-4711 means the upstream certificate expired [1].",
    contexts=["Error E-4711 means the upstream certificate expired."],
    reference="The upstream certificate expired.",
)


def test_deepeval_scores_through_our_provider():
    provider = SchemaJudgeProvider()
    judge = JudgeModel("mistral", provider, "mistral-small-latest")

    scores = asyncio.run(deepeval_evaluator.evaluate(ITEM, judge))

    assert (scores.faithfulness, scores.answer_relevancy, scores.context_precision, scores.context_recall) == (1.0, 1.0, 1.0, 1.0)
    # Every passage agrees with the answer: nothing contradicted.
    assert scores.hallucination == 0.0
    assert scores.rationale
    assert len(judge.calls) >= 5 and {c["model"] for c in provider.calls} == {"mistral-small-latest"}


def test_deepeval_without_a_reference_scores_context_relevancy_and_no_recall():
    judge = JudgeModel("mistral", SchemaJudgeProvider(), "m")
    scores = asyncio.run(deepeval_evaluator.evaluate(EvaluationInput(ITEM.question, ITEM.answer, ITEM.contexts), judge))
    assert scores.context_recall is None and scores.context_precision == 1.0


def test_deepeval_sends_nothing_and_reads_no_env_files():
    from deepeval.config.settings import get_settings
    from deepeval.telemetry.client import telemetry_opt_out

    assert telemetry_opt_out() is True
    assert get_settings().DEEPEVAL_DISABLE_DOTENV is True
