"""Hybrid retrieval: dense vector search plus BM25 keyword search, fused with
reciprocal rank fusion.

Dense search finds passages that mean the same thing in other words; BM25
finds exact terms (names, codes, numbers) that embeddings blur. RRF merges
the two rankings without having to calibrate their very different scores.

Only chunks of the user's own documents with status "ready" are returned.
Vector hits are resolved against the database, so a chunk deleted or
rebuilt since it was indexed is never returned.

On PostgreSQL keyword search runs in the database (see keyword_search), and
only the rows of candidate chunks are loaded, so the cost of a question does
not grow with the size of the user's collection. SQLite scores keywords in
memory.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import metrics, tracing
from app.core.config import settings
from app.models.document import Chunk, Document
from app.services import embedding_service, keyword_search
from app.services.embedding_service import EmbedderFactory, EmbeddingUnavailable
from app.services.embeddings import Embedder, get_embedder
from app.services.llm.base import ProviderError
from app.services.rrf import reciprocal_rank_fusion
from app.services.vector_store import VectorStore, get_vector_store

STRATEGIES = ("hybrid", "dense", "keyword")

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


def _embedding_groups(session: Session, user_id: int, document_ids: list[int] | None):
    """The embedding models of the user's ready documents: (choice, dimension, document count)."""
    query = (
        session.query(Document.embedding_provider, Document.embedding_model, Document.embedding_dimension, func.count())
        .filter(Document.user_id == user_id, Document.status == "ready")
        .group_by(Document.embedding_provider, Document.embedding_model, Document.embedding_dimension)
    )
    if document_ids:
        query = query.filter(Document.id.in_(document_ids))
    groups: dict[tuple, list] = {}
    for provider, model, dimension, count in query.all():
        choice = embedding_service.document_choice(provider, model)
        # Every local document is searched with the current local model.
        key = (choice, None if choice.is_local else dimension)
        groups.setdefault(key, [choice, key[1], 0])[2] += count
    return [tuple(group) for group in groups.values()]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def retrieve(
    session: Session,
    user_id: int,
    query: str,
    k: int | None = None,
    document_ids: list[int] | None = None,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    embedder_factory: EmbedderFactory | None = None,
    warnings: list[str] | None = None,
    strategy: str = "hybrid",
) -> list[RetrievedChunk]:
    """The passages that best answer `query`, best first, at most `k`.

    Documents may have been embedded with different models (see
    embedding_service): the question is embedded once per model and searched
    in that model's collection, and each model's ranking takes part in the
    fusion. If a provider's model can't be used (its key was removed, the
    provider is down), those documents are searched by keyword only, and a
    message saying so is appended to `warnings`.

    `strategy` is "hybrid" (both rankings fused), "dense" (vectors only) or
    "keyword" (keyword search only); experiments compare them.

    `embedder` and `store` replace the local model and its store (tests);
    `embedder_factory` replaces how a provider embedder is built.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown retrieval strategy {strategy!r}")
    started = time.monotonic()
    with tracing.span("rag.retrieve", retrieval__strategy=strategy, retrieval__top_k=k or settings.retrieval_top_k) as current:
        results = _retrieve(
            session, user_id, query, k, document_ids, embedder, store, embedder_factory, warnings, strategy
        )
        current.set_attribute("retrieval.results", len(results))
        if warnings:
            current.set_attribute("retrieval.warnings", len(warnings))
    metrics.RETRIEVAL_DURATION.labels(strategy).observe(time.monotonic() - started)
    return results


def _retrieve(session, user_id, query, k, document_ids, embedder, store, embedder_factory, warnings, strategy):
    k = k or settings.retrieval_top_k
    if not query.strip():
        return []
    candidates = k * CANDIDATE_MULTIPLIER

    # Without a ready document there is nothing to find; don't embed the query
    # or call the vector store (chat still works without documents).
    groups = _embedding_groups(session, user_id, document_ids)
    if not groups:
        return []

    dense_rankings: list[list[int]] = []
    for choice, dimension, count in groups if strategy != "keyword" else ():
        if choice.is_local:
            local = embedder or get_embedder()
            hits = (store or get_vector_store()).search(
                user_id, local.embed_query(query), limit=candidates, document_ids=document_ids
            )
        else:
            group_store = embedding_service.store_for_choice(choice, dimension)
            if group_store is None:
                continue  # indexed without any text, so without vectors
            provider_embedder = None
            try:
                provider_embedder = (embedder_factory or embedding_service.build_embedder)(session, user_id, choice)
                vector = provider_embedder.embed_query(query)
            except (EmbeddingUnavailable, ProviderError) as exc:
                if warnings is not None:
                    reason = exc.message if isinstance(exc, ProviderError) else str(exc)
                    warnings.append(
                        f"{_plural(count, 'document')} embedded with {choice.provider}/{choice.model} "
                        f"could only be searched by keyword: {reason}"
                    )
                continue
            finally:
                if provider_embedder is not None:
                    embedding_service.record_calls(session, user_id, provider_embedder)
            hits = group_store.search(user_id, vector, limit=candidates, document_ids=document_ids)
        dense_rankings.append([hit.chunk_id for hit in hits])

    keyword_ranking = (
        keyword_search.search(session, user_id, query, candidates, document_ids) if strategy != "dense" else []
    )

    # Resolve every candidate against the database at once: this checks that
    # vector hits still belong to a ready document of the user's, and loads
    # what the results need.
    candidate_ids = {chunk_id for ranking in dense_rankings for chunk_id in ranking} | set(keyword_ranking)
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

    dense_rankings = [[chunk_id for chunk_id in ranking if chunk_id in by_id] for ranking in dense_rankings]
    keyword_ranking = [chunk_id for chunk_id in keyword_ranking if chunk_id in by_id]

    # Scores of different embedding models can't be compared, but ranks can:
    # each model's ranking enters the fusion on its own. A chunk is only ever
    # in one of them, since a document is embedded with one model.
    fused = reciprocal_rank_fusion([[str(c) for c in ranking] for ranking in (*dense_rankings, keyword_ranking)])
    dense_pos = {chunk_id: i + 1 for ranking in dense_rankings for i, chunk_id in enumerate(ranking)}
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
