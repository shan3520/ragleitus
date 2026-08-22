"""
Document search and keyword filtering service.

Provides in-memory keyword search, title filtering, and context snippet
extraction for pre-vector keyword matching and fallback search.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Sequence


@dataclass(frozen=True)
class SearchMatch:
    """Represents a search match result with relevance score and snippet."""

    document_id: int
    title: str
    score: float
    snippet: str


def generate_snippet(text: str, query: str, max_length: int = 150) -> str:
    """
    Extract a context snippet around the first occurrence of query in text.

    Parameters
    ----------
    text : str
        Source text.
    query : str
        Search query keyword.
    max_length : int
        Maximum character length of returned snippet.

    Returns
    -------
    str
        Truncated text snippet surrounding the query keyword.
    """
    if not text or not query:
        return (text or "")[:max_length]

    idx = text.lower().find(query.lower())
    if idx == -1:
        snippet = text[:max_length]
        return snippet + ("..." if len(text) > max_length else "")

    start = max(0, idx - max_length // 2)
    end = min(len(text), idx + len(query) + max_length // 2)

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""

    return f"{prefix}{text[start:end].strip()}{suffix}"

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.models.document import UnmatchedSearch, SearchQueryLog, DocumentRetrievalLog


def _log_unmatched_search(session: Session, query: str, duration_ms: float | None = None) -> None:
    try:
        unmatched = UnmatchedSearch(query_text=query, duration_ms=duration_ms, timestamp=datetime.now(timezone.utc))
        session.add(unmatched)
        session.commit()
    except Exception:
        pass


def _log_search(session: Session, query: str, matched_doc_ids: list[int], duration_ms: float | None = None) -> None:
    try:
        query_log = SearchQueryLog(query_text=query, duration_ms=duration_ms, timestamp=datetime.now(timezone.utc))
        session.add(query_log)
        session.flush()
        
        for doc_id in matched_doc_ids:
            retrieval_log = DocumentRetrievalLog(query_log_id=query_log.id, document_id=doc_id)
            session.add(retrieval_log)
        
        session.commit()
    except Exception:
        pass


def search_documents_paginated(
    documents: Sequence,
    query: str,
    get_id: callable = lambda doc: getattr(doc, "id", 0),
    get_title: callable = lambda doc: getattr(doc, "title", ""),
    get_content: callable = lambda doc: getattr(doc, "content", "") or "",
    group_id: int | str | None = None,
    get_group_id: callable = lambda doc: getattr(doc, "group_id", None),
    background_tasks: BackgroundTasks | None = None,
    session: Session | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[int, list[SearchMatch]]:
    """
    Perform a keyword search over documents, returning matches ordered by
    relevance together with the total number of matches.

    Relevance scoring rules:
    - Title match weight: 2.0
    - Content match weight: 1.0

    Parameters
    ----------
    documents : Sequence
        Iterable of document model instances.
    query : str
        Search query keyword.
    limit : int
        Maximum number of matches to return (applied after scoring).
    offset : int
        Number of leading matches to skip before applying ``limit``.

    Returns
    -------
    tuple[int, list[SearchMatch]]
        ``(total_matches, items)`` where ``total_matches`` counts every match
        regardless of pagination and ``items`` is the current page of matches
        sorted by score in descending order.
    """
    start_time = time.perf_counter()

    if not query.strip():
        return 0, []

    q_lower = query.strip().lower()
    matches: list[SearchMatch] = []

    for doc in documents:
        if group_id is not None and get_group_id(doc) != group_id:
            continue

        title = get_title(doc) or ""
        content = get_content(doc) or ""

        score = 0.0
        if q_lower in title.lower():
            score += 2.0
        if q_lower in content.lower():
            score += 1.0

        if score > 0.0:
            snippet = generate_snippet(content, query)
            matches.append(
                SearchMatch(
                    document_id=get_id(doc),
                    title=title,
                    score=score,
                    snippet=snippet,
                )
            )

    matches.sort(key=lambda m: m.score, reverse=True)

    if background_tasks and session:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        if not matches:
            background_tasks.add_task(_log_unmatched_search, session, query, duration_ms=duration_ms)
        else:
            matched_ids = [m.document_id for m in matches]
            background_tasks.add_task(_log_search, session, query, matched_ids, duration_ms=duration_ms)

    total_matches = len(matches)
    items = matches[offset : offset + limit]
    return total_matches, items


def search_documents(
    documents: Sequence,
    query: str,
    get_id: callable = lambda doc: getattr(doc, "id", 0),
    get_title: callable = lambda doc: getattr(doc, "title", ""),
    get_content: callable = lambda doc: getattr(doc, "content", "") or "",
    group_id: int | str | None = None,
    get_group_id: callable = lambda doc: getattr(doc, "group_id", None),
    background_tasks: BackgroundTasks | None = None,
    session: Session | None = None,
) -> list[SearchMatch]:
    """
    Backward-compatible wrapper around :func:`search_documents_paginated`
    that returns only the list of matches.

    Parameters
    ----------
    documents : Sequence
        Iterable of document model instances.
    query : str
        Search query keyword.

    Returns
    -------
    list[SearchMatch]
        Matches sorted by score in descending order.
    """
    _, items = search_documents_paginated(
        documents,
        query,
        get_id=get_id,
        get_title=get_title,
        get_content=get_content,
        group_id=group_id,
        get_group_id=get_group_id,
        background_tasks=background_tasks,
        session=session,
        limit=1000,
    )
    return items
