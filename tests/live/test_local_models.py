"""The server's own models, for real: fastembed downloads them from Hugging Face.

Needs no key, only network access on the first run (the models are cached).
Everything else uses the fake embedder and reranker, so these are the only
tests that run the real local embedding model and cross-encoder.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.embeddings import FastEmbedEmbedder
from app.services.rerankers import FastEmbedReranker
from tests.live.test_providers import PASSAGES, QUESTION, _cosine

pytestmark = pytest.mark.live


def test_the_local_embedder_puts_the_matching_passage_closest():
    embedder = FastEmbedEmbedder(settings.embedding_model, cache_dir=settings.embedding_cache_dir)
    documents = embedder.embed_documents(PASSAGES)
    query = embedder.embed_query(QUESTION)
    assert len(documents) == 2 and len(query) == len(documents[0]) == embedder.dimension
    assert _cosine(query, documents[0]) > _cosine(query, documents[1])


def test_the_local_reranker_scores_the_matching_passage_first():
    reranker = FastEmbedReranker(settings.local_rerank_model, cache_dir=settings.embedding_cache_dir)
    scores = reranker.rerank(QUESTION, PASSAGES)
    assert len(scores) == 2 and scores[0] > scores[1], scores
