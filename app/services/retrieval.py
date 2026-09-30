"""Hybrid retrieval: dense vector search plus BM25 keyword search, fused with
reciprocal rank fusion.

Dense search finds passages that mean the same thing in other words; BM25
finds exact terms (names, codes, numbers) that embeddings blur. RRF merges
the two rankings without having to calibrate their very different scores.

Only chunks of the user's own documents with status "ready" are returned.
Vector hits are resolved against the database, so a chunk deleted or
rebuilt since it was indexed is never returned.

BM25 scores the user's chunks in memory on each query, which is fine for
collections of up to tens of thousands of chunks.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Chunk, Document
from app.services.bm25 import BM25Index
from app.services.embeddings import Embedder, get_embedder
from app.services.rrf import reciprocal_rank_fusion
from app.services.vector_store import VectorStore, get_vector_store

# Each ranker contributes more candidates than are finally returned, so a
# chunk ranked moderately by both can still make the cut after fusion.
CANDIDATE_MULTIPLIER = 4


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_title: str
    page_number: int | None
    content: str
    score: float
    dense_rank: int | None
    keyword_rank: int | None


def retrieve(
    session: Session,
    user_id: int,
    query: str,
    k: int | None = None,
    document_ids: list[int] | None = None,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
) -> list[RetrievedChunk]:
    k = k or settings.retrieval_top_k
    if not query.strip():
        return []
    embedder = embedder or get_embedder()
    store = store or get_vector_store()
    candidates = k * CANDIDATE_MULTIPLIER

    rows_query = (
        session.query(Chunk.id, Chunk.content, Chunk.page_number, Document.id, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.user_id == user_id, Document.status == "ready")
    )
    if document_ids:
        rows_query = rows_query.filter(Document.id.in_(document_ids))
    rows = rows_query.all()
    if not rows:
        return []
    by_id = {row[0]: row for row in rows}

    dense_hits = store.search(user_id, embedder.embed_query(query), limit=candidates, document_ids=document_ids)
    dense_ranking = [hit.chunk_id for hit in dense_hits if hit.chunk_id in by_id]

    keyword_index = BM25Index([row[1] for row in rows])
    keyword_ranking = [rows[i][0] for i, _ in keyword_index.top(query, candidates)]

    fused = reciprocal_rank_fusion([[str(c) for c in dense_ranking], [str(c) for c in keyword_ranking]])
    dense_pos = {chunk_id: i + 1 for i, chunk_id in enumerate(dense_ranking)}
    keyword_pos = {chunk_id: i + 1 for i, chunk_id in enumerate(keyword_ranking)}

    results = []
    for chunk_key, score in fused[:k]:
        chunk_id = int(chunk_key)
        _, content, page_number, document_id, title = by_id[chunk_id]
        results.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                document_title=title,
                page_number=page_number,
                content=content,
                score=score,
                dense_rank=dense_pos.get(chunk_id),
                keyword_rank=keyword_pos.get(chunk_id),
            )
        )
    return results
