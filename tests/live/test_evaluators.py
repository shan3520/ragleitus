"""Ragas and DeepEval through one real provider (each makes several calls per answer).

The provider is LIVE_EVALUATOR_PROVIDER, or the first of openai, gemini,
mistral, together, anthropic, groq that has a key. Ragas also embeds, with
that provider if it offers embeddings.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.services import evaluators, rag_evaluation
from app.services.evaluators import EvaluationInput, JudgeModel
from app.services.llm.embeddings import ProviderEmbedder
from app.services.llm.retry import RetryingProvider
from tests.live.providers import live_provider

PREFERENCE = ("openai", "gemini", "mistral", "together", "anthropic", "groq")

pytestmark = pytest.mark.live


@pytest.fixture
def judge_provider():
    names = [os.environ["LIVE_EVALUATOR_PROVIDER"]] if os.environ.get("LIVE_EVALUATOR_PROVIDER") else PREFERENCE
    for name in names:
        configured = live_provider(name)
        if configured is not None:
            return configured
    pytest.skip("no provider key set for the evaluator tests")


ITEM = EvaluationInput(
    question="What does error E-4711 mean?",
    answer="It means the upstream certificate expired.",
    contexts=["Error E-4711 means the upstream certificate expired. Renew the certificate to clear it."],
    reference="The upstream certificate expired.",
)


@pytest.mark.parametrize("name", ["ragas", "deepeval"])
def test_the_evaluator_libraries_score_through_a_real_provider(judge_provider, name):
    if not evaluators.EVALUATORS[name].installed():
        pytest.skip(f"{name} is not installed")
    embedder = None
    if name == "ragas":
        if not judge_provider.embedding_model:
            pytest.skip(f"Ragas needs embeddings, which {judge_provider.name} does not offer")
        embedder = ProviderEmbedder(judge_provider.name, judge_provider.key, judge_provider.embedding_model, judge_provider.base_url)
    # Retried on rate limits, as experiments call evaluators: these libraries make
    # several calls per answer, more than a free tier allows a minute (Gemini: 5).
    judge = JudgeModel(judge_provider.name, RetryingProvider(judge_provider.provider()), judge_provider.model)
    scores = asyncio.run(rag_evaluation.score(ITEM, judge, name, embedder))
    assert scores.faithfulness is not None and scores.faithfulness >= 0.5, scores
    assert scores.answer_relevancy is not None, scores
    assert judge.calls and all(call.error is None for call in judge.calls)
