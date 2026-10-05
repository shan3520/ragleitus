"""Ragas metrics, judged by the user's own provider and model.

Faithfulness, answer relevancy (which also embeds generated questions, with
the user's embedding model), context precision (against the reference
answer when there is one, otherwise against the answer) and context recall
(reference only). Ragas's own LLM and embedding clients are not used: small
adapters route its calls through our provider adapters and embedders, so
the user's key, provider and telemetry apply as for every other call.

Optional: `pip install ".[ragas]"`. Ragas's usage analytics are switched off.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from functools import lru_cache

from app.services.evaluators._sync import run_sync
from app.services.evaluators.base import EvaluationInput, EvaluatorUnavailable, JudgeModel, Scores, clean_score

NAME = "ragas"
LABEL = "Ragas"
DESCRIPTION = (
    "Ragas faithfulness, answer relevancy, context precision and context recall; "
    "several calls per answer, plus embeddings."
)
NO_PASSAGES = "(No passages were retrieved.)"

# Before Ragas is imported: no usage analytics leave the server.
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")


def installed() -> bool:
    return importlib.util.find_spec("ragas") is not None


class _NotAvailable:
    """Stands in for a LangChain class this installation doesn't have."""


def _langchain_compat() -> None:
    """Ragas 0.4 imports two Vertex AI classes that langchain-community 0.4
    (the release that works with LangChain 1.x, which LangGraph needs) no
    longer has. Ragas only uses them in an isinstance() list, so a stand-in
    class is enough. Real classes are left alone when they exist."""
    import sys
    import types

    try:
        import langchain_community.chat_models.vertexai  # noqa: F401
    except ImportError:
        module = types.ModuleType("langchain_community.chat_models.vertexai")
        module.ChatVertexAI = type("ChatVertexAI", (_NotAvailable,), {})
        sys.modules["langchain_community.chat_models.vertexai"] = module
    import langchain_community.llms as llms

    try:
        llms.VertexAI  # noqa: B018
    except (AttributeError, ImportError):
        llms.VertexAI = type("VertexAI", (_NotAvailable,), {})


@lru_cache(maxsize=1)
def _adapters():
    """The adapter classes, defined once Ragas is known to be importable."""
    _langchain_compat()
    from ragas.embeddings.base import BaseRagasEmbedding
    from ragas.llms.base import InstructorBaseRagasLLM

    class ProviderRagasLLM(InstructorBaseRagasLLM):
        def __init__(self, judge: JudgeModel):
            self.judge = judge

        async def agenerate(self, prompt, response_model):
            return await self.judge.complete_json(prompt, response_model)

        def generate(self, prompt, response_model):
            return run_sync(self.agenerate(prompt, response_model))

    class EmbedderRagasEmbedding(BaseRagasEmbedding):
        """Our Embedder (local or a provider's) as a Ragas embedding."""

        def __init__(self, embedder):
            super().__init__()
            self.embedder = embedder

        def embed_text(self, text, **kwargs):
            return self.embedder.embed_query(text)

        async def aembed_text(self, text, **kwargs):
            return await asyncio.to_thread(self.embedder.embed_query, text)

        def embed_texts(self, texts, **kwargs):
            return self.embedder.embed_documents(list(texts))

        async def aembed_texts(self, texts, **kwargs):
            return await asyncio.to_thread(self.embedder.embed_documents, list(texts))

    return ProviderRagasLLM, EmbedderRagasEmbedding


async def evaluate(item: EvaluationInput, judge: JudgeModel, embedder) -> Scores:
    if not installed():
        raise EvaluatorUnavailable('Ragas is not installed on this server (pip install ".[ragas]").')
    llm_class, embedding_class = _adapters()
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithoutReference,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    llm = llm_class(judge)
    contexts = item.contexts or [NO_PASSAGES]

    faithfulness = await Faithfulness(llm=llm).ascore(
        user_input=item.question, response=item.answer, retrieved_contexts=contexts
    )
    relevancy = await AnswerRelevancy(llm=llm, embeddings=embedding_class(embedder)).ascore(
        user_input=item.question, response=item.answer
    )
    if item.reference:
        precision = await ContextPrecisionWithReference(llm=llm).ascore(
            user_input=item.question, reference=item.reference, retrieved_contexts=contexts
        )
        recall = await ContextRecall(llm=llm).ascore(
            user_input=item.question, retrieved_contexts=contexts, reference=item.reference
        )
    else:
        precision = await ContextPrecisionWithoutReference(llm=llm).ascore(
            user_input=item.question, response=item.answer, retrieved_contexts=contexts
        )
        recall = None
    return Scores(
        faithfulness=clean_score(faithfulness.value),
        answer_relevancy=clean_score(relevancy.value),
        context_precision=clean_score(precision.value),
        context_recall=clean_score(recall.value) if recall is not None else None,
        rationale="Scored with Ragas.",
    )
