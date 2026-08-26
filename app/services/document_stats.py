"""
Service for computing aggregate statistics over a user's document collection.

Pure business logic — no database imports.  Accepts pre-loaded model
instances so the caller (API layer) is responsible for session management.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func

from app.core.errors import NoSearchActivityError
from app.models.document import Document, DocumentRetrievalLog, SearchQueryLog
from app.services.staleness_scoring import compute_staleness_score


@dataclass(frozen=True)
class DocumentStats:
    """Immutable snapshot of collection-level statistics."""

    total_documents: int
    total_chunks: int
    avg_chunks_per_document: float
    status_counts: dict[str, int]
    total_content_length: int
    max_staleness_score: float = 0.0
    avg_staleness_score: float = 0.0
    max_disappointment_ratio: float = 0.0
    avg_disappointment_ratio: float = 0.0


def calculate_document_disappointment_ratio(db, document_id: int, days: int = 30) -> float:
    if not db or document_id is None:
        return 0.0

    from sqlalchemy import func
    from datetime import datetime, timedelta, timezone
    from app.models.feedback import SearchFeedback, document_feedback
    from app.models.document import DocumentRetrievalLog, SearchQueryLog

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    neg_feedbacks = (
        db.query(func.count(SearchFeedback.id))
        .join(document_feedback, SearchFeedback.id == document_feedback.c.search_feedback_id)
        .filter(
            document_feedback.c.document_id == document_id,
            SearchFeedback.is_positive == False,
            SearchFeedback.created_at >= cutoff
        )
        .scalar() or 0
    )

    retrievals = (
        db.query(func.count(DocumentRetrievalLog.id))
        .join(SearchQueryLog, DocumentRetrievalLog.query_log_id == SearchQueryLog.id)
        .filter(
            DocumentRetrievalLog.document_id == document_id,
            SearchQueryLog.timestamp >= cutoff
        )
        .scalar() or 0
    )

    if retrievals == 0:
        return 0.0

    return neg_feedbacks / retrievals


def get_unsearched_documents(session, days: int):
    """
    Return documents created before the cutoff that were not retrieved
    in any search within the last ``days`` days.

    Raises NoSearchActivityError if there were no searches at all in the
    window, because a lack of retrievals is only meaningful when the
    system is actually being used.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    recent_search_count = (
        session.query(func.count(SearchQueryLog.id))
        .filter(SearchQueryLog.timestamp >= cutoff_date)
        .scalar()
    )
    if not recent_search_count:
        raise NoSearchActivityError(
            f"No search activity in the last {days} days; "
            "unsearched documents cannot be determined."
        )

    recently_retrieved_ids = (
        session.query(DocumentRetrievalLog.document_id)
        .join(SearchQueryLog, DocumentRetrievalLog.query_log_id == SearchQueryLog.id)
        .filter(SearchQueryLog.timestamp >= cutoff_date)
        .subquery()
    )

    return (
        session.query(Document)
        .filter(
            Document.created_at < cutoff_date,
            ~Document.id.in_(recently_retrieved_ids.select()),
        )
        .order_by(Document.created_at.desc())
        .all()
    )


def get_underperforming_document_ids(
    session,
    doc_ids: Sequence[int],
    days: int = 30,
    min_retrievals: int = 0,
    min_shown: int | None = None,
) -> set[int]:
    """
    Return the ids of ``doc_ids`` whose retrieval count within the last
    ``days`` days qualifies them as underperforming candidates.

    Documents with zero search returns in the window are strictly excluded:
    they have never been surfaced to a user, so there is no performance
    signal to judge them by. That is the only exclusion applied by default.

    ``min_retrievals`` and ``min_shown`` are optional popularity floors and
    both are off unless a caller asks for them. ``min_retrievals`` used to
    default to 5, which meant a document that upset three people about a
    question nobody else asks was dropped before its feedback was ever
    counted - the retrieval count measures how popular the question was, not
    how much trouble the document caused, and those documents are exactly
    what a needs-attention list is for. A caller that genuinely wants a
    busy-documents view can still ask for one.
    """
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    retrieval_count = func.count(DocumentRetrievalLog.id)

    query = (
        session.query(DocumentRetrievalLog.document_id)
        .join(SearchQueryLog, DocumentRetrievalLog.query_log_id == SearchQueryLog.id)
        .filter(
            SearchQueryLog.timestamp >= start_time,
            DocumentRetrievalLog.document_id.in_(list(doc_ids)),
        )
        .group_by(DocumentRetrievalLog.document_id)
        # Strict exclusion of documents with exactly 0 search returns. This is
        # a signal test, not a popularity test: nothing is known about a
        # document nobody has been shown.
        .having(retrieval_count > 0)
    )
    if min_retrievals:
        query = query.having(retrieval_count >= min_retrievals)
    if min_shown is not None:
        query = query.having(retrieval_count >= min_shown)

    return {row[0] for row in query.all()}


def compute_document_stats(
    documents: Sequence,
    get_chunks: callable = lambda doc: getattr(doc, "chunks", []),
    get_status: callable = lambda doc: getattr(doc, "status", "unknown"),
    get_content: callable = lambda doc: getattr(doc, "content", "") or "",
    db = None,
) -> DocumentStats:
    """
    Compute aggregate stats from a list of document-like objects.

    Parameters
    ----------
    documents : Sequence
        Iterable of document objects.
    get_chunks, get_status, get_content : callable
        Accessor functions to decouple from specific ORM model attributes.

    Returns
    -------
    DocumentStats
    """
    total_documents = len(documents)
    if total_documents == 0:
        return DocumentStats(
            total_documents=0,
            total_chunks=0,
            avg_chunks_per_document=0.0,
            status_counts={},
            total_content_length=0,
        )

    total_chunks = 0
    total_content_length = 0
    status_counts: dict[str, int] = {}
    max_staleness = 0.0
    total_staleness = 0.0
    max_disappointment = 0.0
    total_disappointment = 0.0

    for doc in documents:
        chunks = get_chunks(doc)
        total_chunks += len(chunks)

        status = get_status(doc)
        status_counts[status] = status_counts.get(status, 0) + 1

        content = get_content(doc)
        total_content_length += len(content)
        
        staleness = compute_staleness_score(db, doc)
        total_staleness += staleness
        if staleness > max_staleness:
            max_staleness = staleness

        doc_id = getattr(doc, "id", None)
        ratio = calculate_document_disappointment_ratio(db, doc_id)
        total_disappointment += ratio
        if ratio > max_disappointment:
            max_disappointment = ratio

    avg_chunks = round(total_chunks / total_documents, 2)
    avg_staleness = round(total_staleness / total_documents, 2)
    avg_disappointment = round(total_disappointment / total_documents, 2)

    return DocumentStats(
        total_documents=total_documents,
        total_chunks=total_chunks,
        avg_chunks_per_document=avg_chunks,
        status_counts=status_counts,
        total_content_length=total_content_length,
        max_staleness_score=max_staleness,
        avg_staleness_score=avg_staleness,
        max_disappointment_ratio=max_disappointment,
        avg_disappointment_ratio=avg_disappointment,
    )
