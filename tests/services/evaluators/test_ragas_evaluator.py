import asyncio

import pytest

from app.services.embeddings import FakeEmbedder
from app.services.evaluators import EvaluationInput, JudgeModel, ragas_evaluator
from tests.fakes import SchemaJudgeProvider

pytestmark = pytest.mark.skipif(not ragas_evaluator.installed(), reason="ragas is not installed (pip install \".[ragas]\")")

ITEM = EvaluationInput(
    question="What does error E-4711 mean?",
    answer="Error E-4711 means the upstream certificate expired [1].",
    contexts=["Error E-4711 means the upstream certificate expired."],
    reference="The upstream certificate expired.",
)


class CountingEmbedder(FakeEmbedder):
    def __init__(self):
        super().__init__()
        self.texts: list[str] = []

    def embed_query(self, text):
        self.texts.append(text)
        return super().embed_query(text)

    def embed_documents(self, texts):
        self.texts.extend(texts)
        return super().embed_documents(texts)


def test_ragas_scores_through_our_provider_and_embedder():
    provider = SchemaJudgeProvider()
    judge = JudgeModel("openai", provider, "gpt-4o-mini")
    embedder = CountingEmbedder()

    scores = asyncio.run(ragas_evaluator.evaluate(ITEM, judge, embedder))

    # The fake judge supports every statement: faithful, precise, recalled.
    assert (scores.faithfulness, scores.context_precision, scores.context_recall) == (1.0, 1.0, 1.0)
    assert scores.answer_relevancy is not None
    assert scores.hallucination_score() == 0.0
    # Every LLM call went through our adapter (and so into the judge's log), with the chosen model.
    assert len(judge.calls) >= 5 and len(provider.calls) == len(judge.calls)
    assert {c["model"] for c in provider.calls} == {"gpt-4o-mini"}
    # Answer relevancy embedded the question with our embedder.
    assert ITEM.question in embedder.texts


def test_ragas_without_a_reference_has_no_recall():
    judge = JudgeModel("openai", SchemaJudgeProvider(), "m")
    item = EvaluationInput(ITEM.question, ITEM.answer, [], None)
    scores = asyncio.run(ragas_evaluator.evaluate(item, judge, FakeEmbedder()))
    assert scores.context_recall is None and scores.context_precision is not None


def test_ragas_analytics_are_off():
    import os

    assert os.environ["RAGAS_DO_NOT_TRACK"] == "true"
