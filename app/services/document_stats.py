"""
Service for computing aggregate statistics over a user's document collection.

Pure business logic — no database imports.  Accepts pre-loaded model
instances so the caller (API layer) is responsible for session management.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class DocumentStats:
    """Immutable snapshot of collection-level statistics."""

    total_documents: int
    total_chunks: int
    avg_chunks_per_document: float
    status_counts: dict[str, int]
    total_content_length: int


def compute_document_stats(
    documents: Sequence,
    get_chunks: callable = lambda doc: getattr(doc, "chunks", []),
    get_status: callable = lambda doc: getattr(doc, "status", "unknown"),
    get_content: callable = lambda doc: getattr(doc, "content", "") or "",
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

    for doc in documents:
        chunks = get_chunks(doc)
        total_chunks += len(chunks)

        status = get_status(doc)
        status_counts[status] = status_counts.get(status, 0) + 1

        content = get_content(doc)
        total_content_length += len(content)

    avg_chunks = round(total_chunks / total_documents, 2)

    return DocumentStats(
        total_documents=total_documents,
        total_chunks=total_chunks,
        avg_chunks_per_document=avg_chunks,
        status_counts=status_counts,
        total_content_length=total_content_length,
    )
