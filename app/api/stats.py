from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.errors import NoSearchActivityError
from app.db.database import get_db
from app.services.document_service import list_user_documents
from app.services.document_stats import compute_document_stats, calculate_document_disappointment_ratio, get_unsearched_documents, get_underperforming_document_ids
from app.services.usage_analytics import get_search_analytics_or_empty, get_popular_searches, get_popular_documents, get_daily_search_latency
from pydantic import BaseModel, ConfigDict
from typing import List
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import func
from app.models.document import DocumentRetrievalLog, SearchQueryLog

class PopularSearch(BaseModel):
    query: str
    count: int

class PopularDocument(BaseModel):
    document_id: int
    count: int

class DailySearchLatency(BaseModel):
    date: date
    total_searches: int
    average_duration_ms: float
    max_duration_ms: float

router = APIRouter(tags=["stats"])

@router.get("/api/stats/popular-searches", response_model=List[PopularSearch])
def api_popular_searches(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
    days: int = 30,
    limit: int = 10,
):
    return get_popular_searches(session, days=days, limit=limit)

@router.get("/api/stats/popular-documents", response_model=List[PopularDocument])
def api_popular_documents(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
    days: int = 30,
    limit: int = 10,
):
    return get_popular_documents(session, days=days, limit=limit)

@router.get("/api/stats/search-latency", response_model=list[DailySearchLatency])
def api_daily_search_latency(
    session: Session = Depends(get_db),
    days: int = 30,
):
    return get_daily_search_latency(session, days)


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
    search_analytics = get_search_analytics_or_empty(session, days=days)
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
    min_shown: int | None = None,
):
    documents = list_user_documents(session, user["username"])
    if not documents:
        return []

    doc_ids = [doc.id for doc in documents]
    valid_doc_ids = get_underperforming_document_ids(
        session,
        doc_ids,
        days=days,
        min_retrievals=min_retrievals,
        min_shown=min_shown,
    )

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


@router.get("/api/stats/unsearched-documents")
def api_unsearched_documents(
    user: dict = Depends(get_current_user),
    days: int = 30,
    db: Session = Depends(get_db),
):
    """
    Get documents that existed before the cutoff and were not retrieved in
    any search within the last ``days`` days.
    """
    try:
        documents = get_unsearched_documents(db, days)
    except NoSearchActivityError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return [
        {
            "id": doc.id,
            "title": doc.title,
            "status": doc.status,
            "created_at": doc.created_at,
        }
        for doc in documents
    ]


class DeadDocumentResponse(BaseModel):
    id: int
    title: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/dead-documents", response_model=list[DeadDocumentResponse])
@router.get("/stats/dead-documents", response_model=list[DeadDocumentResponse])
def api_dead_documents(days: int = 30, db: Session = Depends(get_db)):
    """
    Get documents that existed before the cutoff and were not retrieved in
    any search within the last ``days`` days, newest first. Returns a plain
    text warning when there is no search activity to compare against.
    """
    try:
        documents = get_unsearched_documents(db, days)
    except NoSearchActivityError as e:
        return Response(content=str(e), status_code=400, media_type="text/plain")

    return sorted(documents, key=lambda doc: doc.created_at, reverse=True)
