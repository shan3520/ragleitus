"""Text embedding.

`fastembed` runs a small ONNX model locally, so indexing needs no API key and
no GPU; the model is downloaded once on first use and cached. `fake` is a
deterministic hashing embedder for tests and offline development: texts that
share words get similar vectors, which is enough to exercise retrieval.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class FakeEmbedder:
    model_name = "fake-hash"

    def __init__(self, dimension: int = 256):
        self.dimension = dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in re.findall(r"\w+", text.lower()):
            digest = hashlib.md5(token.encode()).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FastEmbedEmbedder:
    def __init__(self, model_name: str, cache_dir: str | None = None):
        from fastembed import TextEmbedding

        supported = {m["model"]: m for m in TextEmbedding.list_supported_models()}
        if model_name not in supported:
            raise ValueError(f"fastembed does not support embedding model {model_name!r}")
        self.model_name = model_name
        self.dimension = int(supported[model_name]["dim"])
        self._model_cls = TextEmbedding
        self._cache_dir = cache_dir
        self._model = None

    def _load(self):
        # Loading downloads the model on first use; defer it until it is needed.
        if self._model is None:
            self._model = self._model_cls(self.model_name, cache_dir=self._cache_dir)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._load().passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._load().query_embed(text))).tolist()


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if settings.embedding_backend == "fake":
        return FakeEmbedder()
    return FastEmbedEmbedder(settings.embedding_model, cache_dir=settings.embedding_cache_dir)
