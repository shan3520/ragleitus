"""Rerankers: score how well each candidate passage answers a question.

Retrieval finds candidates by meaning (vectors) and by words (keywords) and
fuses the two rankings; a reranker then reads the question and each
candidate together, which is slower but sharper, and puts the best first.

`local` runs a small cross-encoder on this server with fastembed (the same
library as the local embedding model, so no new dependency; the model is
downloaded once on first use). `fake` (RERANK_BACKEND=fake) scores by shared
words, for tests. Providers' rerank APIs are in app.services.llm.rerank.
"""

from __future__ import annotations

import re
import threading
from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class Reranker(Protocol):
    model_name: str

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """A relevance score for each passage, in the order given (higher is better)."""
        ...


_WORD = re.compile(r"\w+")


class FakeReranker:
    """Scores a passage by the share of the question's words it contains."""

    model_name = "fake-overlap"

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        words = set(_WORD.findall(query.lower()))
        if not words:
            return [0.0] * len(passages)
        return [len(words & set(_WORD.findall(p.lower()))) / len(words) for p in passages]


class FastEmbedReranker:
    """A cross-encoder run locally by fastembed."""

    def __init__(self, model_name: str, cache_dir: str | None = None):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        supported = {m["model"] for m in TextCrossEncoder.list_supported_models()}
        if model_name not in supported:
            raise ValueError(f"fastembed does not support reranking model {model_name!r}")
        self.model_name = model_name
        self._model_cls = TextCrossEncoder
        self._cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        # Loading downloads the model on first use; several experiment threads may ask at once.
        with self._lock:
            if self._model is None:
                self._model = self._model_cls(self.model_name, cache_dir=self._cache_dir)
            return self._model

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(score) for score in self._load().rerank(query, passages)]


@lru_cache(maxsize=1)
def get_local_reranker() -> Reranker:
    if settings.rerank_backend == "fake":
        return FakeReranker()
    return FastEmbedReranker(settings.local_rerank_model, cache_dir=settings.embedding_cache_dir)
