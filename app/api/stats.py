from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.services.document_service import list_user_documents
from app.services.document_stats import compute_document_stats, calculate_document_disappointment_ratio
from app.services.usage_analytics import get_search_analytics, get_popular_searches, get_popular_documents
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
from app.models.document import DocumentRetrievalLog, SearchQueryLog

class PopularSearch(BaseModel):
    query: str
    count: int

class PopularDocument(BaseModel):
    document_id: int
    count: int

router = APIRouter(tags=["stats"])

@router.get("/api/stats/popular-searches", response_model=List[PopularSearch])
def api_popular_searches(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
    days: int = 7,
    limit: int = 10,
):
    return get_popular_searches(session, days=days, limit=limit)

@router.get("/api/stats/popular-documents", response_model=List[PopularDocument])
def api_popular_documents(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
    days: int = 7,
    limit: int = 10,
):
    return get_popular_documents(session, days=days, limit=limit)


@router.get("/api/documents/stats")
def get_collection_stats(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
    days: int = 7,
):
    """
    Get aggregate document collection statistics for the current user.
    """
    documents = list_user_documents(session, user["username"])
    stats = compute_document_stats(documents)
    search_analytics = get_search_analytics(session, days=days)
    return {
        "total_documents": stats.total_documents,
        "total_chunks": stats.total_chunks,
        "avg_chunks_per_document": stats.avg_chunks_per_document,
        "status_counts": stats.status_counts,
        "total_content_length": stats.total_content_length,
        "search_analytics": search_analytics,
    }

class UnderperformingDocument(BaseModel):
    document_id: int
    title: str
    disappointment_ratio: float

@router.get("/api/stats/underperforming-documents", response_model=List[UnderperformingDocument])
def api_underperforming_documents(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
    min_retrievals: int = 5,
    days: int = 30,
):
    documents = list_user_documents(session, user["username"])
    if not documents:
        return []

    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    doc_ids = [doc.id for doc in documents]
    
    doc_counts = session.query(
        DocumentRetrievalLog.document_id,
        func.count(DocumentRetrievalLog.id).label('count')
    ).join(
        SearchQueryLog, DocumentRetrievalLog.query_log_id == SearchQueryLog.id
    ).filter(
        SearchQueryLog.timestamp >= start_time,
        DocumentRetrievalLog.document_id.in_(doc_ids)
    ).group_by(
        DocumentRetrievalLog.document_id
    ).having(
        func.count(DocumentRetrievalLog.id) >= min_retrievals
    ).all()
    
    valid_doc_ids = {row[0] for row in doc_counts}
    
    result = []
    for doc in documents:
        if doc.id in valid_doc_ids:
            ratio = calculate_document_disappointment_ratio(session, doc.id, days=days)
            result.append(UnderperformingDocument(
                document_id=doc.id,
                title=doc.title,
                disappointment_ratio=ratio
            ))
            
    result.sort(key=lambda x: x.disappointment_ratio, reverse=True)
    return result
