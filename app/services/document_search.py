"""
Document search and keyword filtering service.

Provides in-memory keyword search, title filtering, and context snippet
extraction for pre-vector keyword matching and fallback search.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def search_documents(
    documents: Sequence,
    query: str,
    get_id: callable = lambda doc: getattr(doc, "id", 0),
    get_title: callable = lambda doc: getattr(doc, "title", ""),
    get_content: callable = lambda doc: getattr(doc, "content", "") or "",
) -> list[SearchMatch]:
    """
    Perform a keyword search over documents, returning matches ordered by relevance.

    Relevance scoring rules:
    - Title match weight: 2.0
    - Content match weight: 1.0

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
    if not query.strip():
        return []

    q_lower = query.strip().lower()
    matches: list[SearchMatch] = []

    for doc in documents:
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
    return matches
