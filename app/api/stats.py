from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.services.document_service import list_user_documents
from app.services.document_stats import compute_document_stats
from app.services.usage_analytics import get_search_analytics, get_popular_searches, get_popular_documents
from pydantic import BaseModel
from typing import List

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
