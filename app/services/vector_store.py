"""Chunk vectors in Qdrant.

Points carry only identifiers (user, document, chunk, page); chunk text lives
in the SQL `chunks` table. Every search and delete is filtered by `user_id`,
so one user's vectors can never be returned for another user's query.

`VECTOR_STORE_URL` selects the Qdrant mode: an http(s) URL for a server,
":memory:" for an in-process store, anything else is a local directory for
Qdrant's embedded mode.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.services.embeddings import get_embedder


@dataclass(frozen=True)
class ChunkVector:
    chunk_id: int
    page_number: int | None
    vector: list[float]


@dataclass(frozen=True)
class VectorHit:
    chunk_id: int
    document_id: int
    score: float


def _match(key: str, value) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


class VectorStore:
    def __init__(self, client: QdrantClient, model_name: str, dimension: int, payload_indexes: bool = False):
        self.client = client
        self._payload_indexes = payload_indexes
        self.dimension = dimension
        slug = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_")
        self.collection = f"chunks_{slug}_{dimension}"
        self._ready = False
        self._lock = threading.Lock()

    def ensure_collection(self) -> None:
        if self._ready:
            return
        # Background indexing tasks run concurrently, and another process may
        # create the collection at the same moment: serialise creation here and
        # treat "already exists" as success.
        with self._lock:
            if self._ready:
                return
            if not self.client.collection_exists(self.collection):
                try:
                    self.client.create_collection(
                        self.collection,
                        vectors_config=models.VectorParams(size=self.dimension, distance=models.Distance.COSINE),
                    )
                except Exception:
                    if not self.client.collection_exists(self.collection):
                        raise
                # Only a Qdrant server uses payload indexes; embedded mode ignores them.
                for field in ("user_id", "document_id") if self._payload_indexes else ():
                    self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.INTEGER)
            self._ready = True

    def upsert_document(self, user_id: int, document_id: int, chunks: list[ChunkVector]) -> None:
        self.ensure_collection()
        if not chunks:
            return
        self.client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=chunk.chunk_id,
                    vector=chunk.vector,
                    payload={
                        "user_id": user_id,
                        "document_id": document_id,
                        "chunk_id": chunk.chunk_id,
                        "page_number": chunk.page_number,
                    },
                )
                for chunk in chunks
            ],
        )

    def delete_documents(self, user_id: int, document_ids: list[int]) -> None:
        if not document_ids:
            return
        self.ensure_collection()
        self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        _match("user_id", user_id),
                        models.FieldCondition(key="document_id", match=models.MatchAny(any=list(document_ids))),
                    ]
                )
            ),
        )

    def delete_points(self, chunk_ids: list[int]) -> None:
        """Delete specific vectors by chunk id (point ids are chunk ids)."""
        if not chunk_ids:
            return
        self.ensure_collection()
        self.client.delete(self.collection, points_selector=models.PointIdsList(points=list(chunk_ids)))

    def search(self, user_id: int, vector: list[float], limit: int, document_ids: list[int] | None = None) -> list[VectorHit]:
        self.ensure_collection()
        conditions = [_match("user_id", user_id)]
        if document_ids:
            conditions.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=list(document_ids))))
        result = self.client.query_points(
            self.collection,
            query=vector,
            limit=limit,
            query_filter=models.Filter(must=conditions),
            with_payload=True,
        )
        return [
            VectorHit(chunk_id=int(p.payload["chunk_id"]), document_id=int(p.payload["document_id"]), score=float(p.score))
            for p in result.points
        ]

    def count(self, user_id: int, document_id: int | None = None) -> int:
        self.ensure_collection()
        conditions = [_match("user_id", user_id)]
        if document_id is not None:
            conditions.append(_match("document_id", document_id))
        return self.client.count(self.collection, count_filter=models.Filter(must=conditions), exact=True).count

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False


def _make_client(url: str) -> QdrantClient:
    if url == ":memory:":
        return QdrantClient(location=":memory:")
    if url.startswith(("http://", "https://")):
        return QdrantClient(url=url, api_key=settings.vector_store_api_key.get_secret_value() or None)
    return QdrantClient(path=url)


@lru_cache(maxsize=1)
def _client() -> QdrantClient:
    return _make_client(settings.vector_store_url)


@lru_cache(maxsize=64)
def store_for(model_name: str, dimension: int) -> VectorStore:
    """The vector store (one collection) for an embedding model; all share one client."""
    return VectorStore(
        _client(),
        model_name,
        dimension,
        payload_indexes=settings.vector_store_url.startswith(("http://", "https://")),
    )


def get_vector_store() -> VectorStore:
    """The store for the server's own (local) embedding model."""
    embedder = get_embedder()
    return store_for(embedder.model_name, embedder.dimension)
