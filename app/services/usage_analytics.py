from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.core.errors import NoSearchActivityError
from app.models.document import SearchQueryLog, DocumentRetrievalLog

def get_search_analytics(db: Session, days: int = 30) -> dict:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)

    recent_query_count = (
        db.query(func.count(SearchQueryLog.id))
        .filter(SearchQueryLog.timestamp >= start_time)
        .scalar()
    )
    if not recent_query_count:
        raise NoSearchActivityError(
            f"No search activity in the last {days} days."
        )

    query_counts = db.query(
        SearchQueryLog.query_text, 
        func.count(SearchQueryLog.id).label('count')
    ).filter(
        SearchQueryLog.timestamp >= start_time
    ).group_by(
        SearchQueryLog.query_text
    ).order_by(
        desc('count'),
        SearchQueryLog.query_text
    ).all()
    
    top_queries = [{"query": row[0], "count": row[1]} for row in query_counts]
    
    doc_counts = db.query(
        DocumentRetrievalLog.document_id,
        func.count(DocumentRetrievalLog.id).label('count')
    ).join(
        SearchQueryLog
    ).filter(
        SearchQueryLog.timestamp >= start_time
    ).group_by(
        DocumentRetrievalLog.document_id
    ).order_by(
        desc('count'),
        DocumentRetrievalLog.document_id
    ).all()
    
    top_documents = [{"document_id": row[0], "count": row[1]} for row in doc_counts]
    
    return {
        "top_queries": top_queries,
        "top_documents": top_documents
    }

def get_popular_searches(db: Session, days: int = 30, limit: int = 10) -> list[dict]:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)

    recent_query_count = (
        db.query(func.count(SearchQueryLog.id))
        .filter(SearchQueryLog.timestamp >= start_time)
        .scalar()
    )
    if not recent_query_count:
        raise NoSearchActivityError(
            f"No search activity in the last {days} days."
        )

    query_counts = db.query(
        SearchQueryLog.query_text, 
        func.count(SearchQueryLog.id).label('count')
    ).filter(
        SearchQueryLog.timestamp >= start_time
    ).group_by(
        SearchQueryLog.query_text
    ).order_by(
        desc('count'),
        SearchQueryLog.query_text
    ).limit(limit).all()
    
    return [{"query": row[0], "count": row[1]} for row in query_counts]

def get_popular_documents(db: Session, days: int = 30, limit: int = 10) -> list[dict]:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)

    recent_query_count = (
        db.query(func.count(SearchQueryLog.id))
        .filter(SearchQueryLog.timestamp >= start_time)
        .scalar()
    )
    if not recent_query_count:
        raise NoSearchActivityError(
            f"No search activity in the last {days} days."
        )

    doc_counts = db.query(
        DocumentRetrievalLog.document_id,
        func.count(DocumentRetrievalLog.id).label('count')
    ).join(
        SearchQueryLog
    ).filter(
        SearchQueryLog.timestamp >= start_time
    ).group_by(
        DocumentRetrievalLog.document_id
    ).order_by(
        desc('count'),
        DocumentRetrievalLog.document_id
    ).limit(limit).all()
    
    return [{"document_id": row[0], "count": row[1]} for row in doc_counts]

def get_search_analytics_or_empty(db: Session, days: int = 30) -> dict:
    """Variant of get_search_analytics that treats an empty activity window
    as empty results instead of raising. Used by the collection-stats
    endpoint, whose contract is to always return 200 with an analytics
    payload regardless of search activity."""
    try:
        return get_search_analytics(db, days=days)
    except NoSearchActivityError:
        return {"top_queries": [], "top_documents": []}
