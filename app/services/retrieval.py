"""Hybrid retrieval: dense vector search plus BM25 keyword search, fused with
reciprocal rank fusion.

Dense search finds passages that mean the same thing in other words; BM25
finds exact terms (names, codes, numbers) that embeddings blur. RRF merges
the two rankings without having to calibrate their very different scores.

Only chunks of the user's own documents with status "ready" are returned.
Vector hits are resolved against the database, so a chunk deleted or
rebuilt since it was indexed is never returned.

Keyword search runs in the database where it can (see keyword_search), and
only the rows of the chunks that are returned are loaded, so the cost of a
query does not grow with the size of the user's collection.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Chunk, Document
from app.services import keyword_search
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

    dense_hits = store.search(user_id, embedder.embed_query(query), limit=candidates, document_ids=document_ids)
    keyword_ranking = keyword_search.search(session, user_id, query, candidates, document_ids)

    # Resolve every candidate against the database at once: this checks that
    # vector hits still belong to a ready document of the user's, and loads
    # what the results need.
    candidate_ids = {hit.chunk_id for hit in dense_hits} | set(keyword_ranking)
    if not candidate_ids:
        return []
    rows_query = (
        session.query(Chunk.id, Chunk.content, Chunk.page_number, Document.id, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .filter(Chunk.id.in_(candidate_ids), Document.user_id == user_id, Document.status == "ready")
    )
    if document_ids:
        rows_query = rows_query.filter(Document.id.in_(document_ids))
    by_id = {row[0]: row for row in rows_query.all()}

    dense_ranking = [hit.chunk_id for hit in dense_hits if hit.chunk_id in by_id]
    keyword_ranking = [chunk_id for chunk_id in keyword_ranking if chunk_id in by_id]

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
