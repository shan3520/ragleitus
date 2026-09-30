from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.core.errors import NoSearchActivityError
from app.models.document import SearchQueryLog, DocumentRetrievalLog

# Every function takes an optional ``user_id``. Route handlers always pass the
# authenticated user's id so one user's activity never shows up in another
# user's analytics; ``None`` means no ownership filter.


def _in_window(query, start_time: datetime, user_id: int | None):
    query = query.filter(SearchQueryLog.timestamp >= start_time)
    if user_id is not None:
        query = query.filter(SearchQueryLog.user_id == user_id)
    return query


def _require_activity(db: Session, start_time: datetime, days: int, user_id: int | None) -> None:
    recent_query_count = _in_window(db.query(func.count(SearchQueryLog.id)), start_time, user_id).scalar()
    if not recent_query_count:
        raise NoSearchActivityError(
            f"No search activity in the last {days} days."
        )


def _query_counts(db: Session, start_time: datetime, user_id: int | None):
    return _in_window(
        db.query(SearchQueryLog.query_text, func.count(SearchQueryLog.id).label('count')),
        start_time,
        user_id,
    ).group_by(
        SearchQueryLog.query_text
    ).order_by(
        desc('count'),
        SearchQueryLog.query_text
    )


def _document_counts(db: Session, start_time: datetime, user_id: int | None):
    return _in_window(
        db.query(
            DocumentRetrievalLog.document_id,
            func.count(DocumentRetrievalLog.id).label('count')
        ).join(SearchQueryLog),
        start_time,
        user_id,
    ).group_by(
        DocumentRetrievalLog.document_id
    ).order_by(
        desc('count'),
        DocumentRetrievalLog.document_id
    )


def get_search_analytics(db: Session, days: int = 30, user_id: int | None = None) -> dict:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    _require_activity(db, start_time, days, user_id)

    top_queries = [{"query": row[0], "count": row[1]} for row in _query_counts(db, start_time, user_id).all()]
    top_documents = [{"document_id": row[0], "count": row[1]} for row in _document_counts(db, start_time, user_id).all()]

    return {
        "top_queries": top_queries,
        "top_documents": top_documents
    }


def get_popular_searches(db: Session, days: int = 30, limit: int = 10, user_id: int | None = None) -> list[dict]:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    _require_activity(db, start_time, days, user_id)

    rows = _query_counts(db, start_time, user_id).limit(limit).all()
    return [{"query": row[0], "count": row[1]} for row in rows]


def get_daily_search_latency(db: Session, days: int = 30, user_id: int | None = None) -> list[dict]:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)

    rows = _in_window(
        db.query(
            func.date(SearchQueryLog.timestamp).label('date'),
            func.count(SearchQueryLog.id).label('total_searches'),
            func.avg(SearchQueryLog.duration_ms).label('average_duration_ms'),
            func.max(SearchQueryLog.duration_ms).label('max_duration_ms'),
        ),
        start_time,
        user_id,
    ).group_by(
        func.date(SearchQueryLog.timestamp)
    ).order_by(
        func.date(SearchQueryLog.timestamp)
    ).all()

    return [
        {
            "date": row.date,
            "total_searches": row.total_searches,
            "average_duration_ms": float(row.average_duration_ms) if row.average_duration_ms is not None else 0.0,
            "max_duration_ms": float(row.max_duration_ms) if row.max_duration_ms is not None else 0.0,
        }
        for row in rows
    ]


def get_popular_documents(db: Session, days: int = 30, limit: int = 10, user_id: int | None = None) -> list[dict]:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    _require_activity(db, start_time, days, user_id)

    rows = _document_counts(db, start_time, user_id).limit(limit).all()
    return [{"document_id": row[0], "count": row[1]} for row in rows]


def get_search_analytics_or_empty(db: Session, days: int = 30, user_id: int | None = None) -> dict:
    """Variant of get_search_analytics that treats an empty activity window
    as empty results instead of raising. Used by the collection-stats
    endpoint, whose contract is to always return 200 with an analytics
    payload regardless of search activity."""
    try:
        return get_search_analytics(db, days=days, user_id=user_id)
    except NoSearchActivityError:
        return {"top_queries": [], "top_documents": []}
