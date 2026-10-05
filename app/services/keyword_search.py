"""Keyword search over a user's indexed chunks.

On PostgreSQL the database does the work: chunks carry a generated
`search_vector` (tsvector) column with a GIN index (migration 0025), and a
query touches only the chunks that contain one of its terms, ranks them in
SQL and returns the top few ids. Nothing is loaded into Python but the ids.

The ranking is BM25-like. Terms match on any one of them, as in BM25, rather
than requiring all. Each term is weighted by how rare it is (inverse document
frequency), and `ts_rank` with length normalisation stands in for the
saturating term frequency. How common a term is comes from the statistics
PostgreSQL keeps on the column anyway (`pg_stats`, refreshed by ANALYZE and
autovacuum), so weighting costs no extra query per search. Those statistics
cover all chunks, not one user's, which is how search engines weight terms
too; until the table has been analysed every term weighs the same.

Other databases (SQLite in development and tests) have no such index; there
the user's chunks are scored in memory with `BM25Index`, which is fine for
collections of up to tens of thousands of chunks.

The `search_vector` column is deliberately not mapped on the Chunk model: it
exists only on PostgreSQL, so queries name it directly.
"""

from __future__ import annotations

import math
import threading
import time
from functools import reduce

from sqlalchemy import Float, and_, bindparam, func, literal_column, select, text
from sqlalchemy.orm import Session

from app.models.document import Chunk, Document
from app.services.bm25 import BM25Index, tokenize

# Text search configuration of the generated column and of the queries. They
# must match, or terms would be normalised differently on the two sides.
# 'simple' lowercases without stemming or stop words, so codes, names and
# numbers in any language match exactly.
TS_CONFIG = "simple"

# A query is cut to this many distinct terms; longer ones are pasted text,
# not keyword searches.
MAX_TERMS = 32

# Words so common that matching them says nothing. They are left out of the
# query (unless nothing else is left), which keeps a question like "what is
# the ..." from matching nearly every chunk; BM25 in memory weights them down
# by their frequency anyway.
STOP_WORDS = frozenset(
    "a an and are as at be but by can did do does for from had has have how i if in into is it its "
    "me my no not of on or our so than that the their them then there these they this to was we "
    "were what when where which who why will with you your".split()
)

# Terms found in more than this share of chunks are dropped from the
# PostgreSQL query when rarer terms remain: they score next to nothing but
# would make the query match, and rank, nearly every chunk.
COMMON_TERM_FRACTION = 0.5

# The highest share of chunks assumed for a term the statistics don't list
# (PostgreSQL's DEFAULT_TS_MATCH_SEL).
UNLISTED_TERM_FREQUENCY = 0.005

# How long term statistics are reused before being read again.
STATS_TTL_SECONDS = 300

search_vector = literal_column("chunks.search_vector")


def query_terms(query: str) -> list[str]:
    """Distinct lowercase terms of the query, stop words removed unless that leaves none."""
    terms = list(dict.fromkeys(tokenize(query)))
    content = [t for t in terms if t not in STOP_WORDS]
    return (content or terms)[:MAX_TERMS]


def _candidate_filter(user_id: int, document_ids: list[int] | None):
    condition = and_(Document.user_id == user_id, Document.status == "ready")
    if document_ids:
        condition = and_(condition, Document.id.in_(document_ids))
    return condition


def search(
    session: Session,
    user_id: int,
    query: str,
    limit: int,
    document_ids: list[int] | None = None,
) -> list[int]:
    """Ids of the user's best-matching chunks, best first, at most `limit`.

    Only chunks of the user's own ready documents (optionally only of
    `document_ids`) are considered; chunks matching no term are left out.
    """
    if limit <= 0 or not tokenize(query):
        return []
    if session.get_bind().dialect.name == "postgresql":
        return _search_postgres(session, user_id, query, limit, document_ids)
    return _search_in_memory(session, user_id, query, limit, document_ids)


def _search_in_memory(session, user_id, query, limit, document_ids) -> list[int]:
    rows = session.execute(
        select(Chunk.id, Chunk.content)
        .join(Document, Chunk.document_id == Document.id)
        .where(_candidate_filter(user_id, document_ids))
    ).all()
    if not rows:
        return []
    index = BM25Index([content for _, content in rows])
    return [rows[i][0] for i, _ in index.top(query, limit)]


class TermStatistics:
    """The share of chunks each common term appears in, from `pg_stats`.

    ANALYZE samples the column and records its most common lexemes with their
    frequencies, plus the lowest frequency it recorded. A term not listed is
    rarer than that; like PostgreSQL's own estimate for text search, take half
    the lowest listed frequency, but no more than 0.5%.
    """

    def __init__(self, frequencies: dict[str, float], floor: float):
        self.frequencies = frequencies
        self.floor = floor

    def frequency(self, term: str) -> float:
        return self.frequencies.get(term, min(self.floor / 2, UNLISTED_TERM_FREQUENCY))

    def idf(self, term: str) -> float:
        # BM25's IDF on fractions: always positive, near zero for terms in
        # most chunks.
        f = self.frequency(term)
        return math.log(1 + (1 - f + 1e-6) / (f + 1e-6))


_stats_lock = threading.Lock()
_stats_cache: dict[str, tuple[float, TermStatistics | None]] = {}


def term_statistics(session: Session) -> TermStatistics | None:
    """Statistics for the search_vector column, or None before it is analysed."""
    key = session.get_bind().engine.url.render_as_string(hide_password=True)
    now = time.monotonic()
    with _stats_lock:
        cached = _stats_cache.get(key)
        if cached and now - cached[0] < STATS_TTL_SECONDS:
            return cached[1]
    row = session.execute(
        text(
            "SELECT most_common_elems::text::text[], most_common_elem_freqs FROM pg_stats "
            "WHERE schemaname = current_schema() AND tablename = 'chunks' AND attname = 'search_vector'"
        )
    ).first()
    stats = None
    if row and row[0] and row[1]:
        elems, freqs = row
        # The frequencies are followed by the minimum, maximum and null share.
        stats = TermStatistics(dict(zip(elems, freqs)), floor=freqs[len(elems)])
    with _stats_lock:
        _stats_cache[key] = (now, stats)
    return stats


def ranking_statement(user_id: int, terms: list[str], weights: list[float], limit: int, document_ids):
    """The top chunks matching any term, ranked by IDF-weighted ts_rank.

    Each term is a bound parameter parsed by plainto_tsquery, so nothing in the
    query is ever interpreted as tsquery syntax or SQL.
    """
    queries = [
        func.plainto_tsquery(literal_column(f"'{TS_CONFIG}'"), bindparam(f"term_{i}", term))
        for i, term in enumerate(terms)
    ]
    any_term = reduce(lambda a, b: a.op("||")(b), queries)
    # Normalisation 1 divides by 1 + log(length), so long chunks don't win
    # just by repeating a term.
    score = reduce(
        lambda a, b: a + b,
        [
            bindparam(f"weight_{i}", weight, type_=Float) * func.ts_rank(search_vector, q, 1)
            for i, (q, weight) in enumerate(zip(queries, weights))
        ],
    )
    return (
        select(Chunk.id)
        .join(Document, Chunk.document_id == Document.id)
        .where(_candidate_filter(user_id, document_ids), search_vector.op("@@")(any_term))
        .order_by(score.desc(), Chunk.id)
        .limit(limit)
    )


def weighted_terms(terms: list[str], stats: TermStatistics | None) -> list[tuple[str, float]]:
    """The terms to search for, each with its weight."""
    if stats is None:
        return [(term, 1.0) for term in terms]
    selective = [t for t in terms if stats.frequency(t) <= COMMON_TERM_FRACTION]
    return [(term, stats.idf(term)) for term in selective or terms]


def _search_postgres(session, user_id, query, limit, document_ids) -> list[int]:
    terms = weighted_terms(query_terms(query), term_statistics(session))
    statement = ranking_statement(
        user_id, [term for term, _ in terms], [weight for _, weight in terms], limit, document_ids
    )
    return list(session.execute(statement).scalars())
