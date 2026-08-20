from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from app.db.database import get_db
from app.models.document import UnmatchedSearch
from app.models.query_cluster import QueryCluster
from app.api.auth import get_current_user
from app.services.query_similarity import compute_query_similarity_matrix
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/unanswered-queries", tags=["analytics"])


@router.get("/recent")
def get_recent_queries(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: str = Query("open"),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get recent unanswered queries, paginated.
    """
    query = session.query(UnmatchedSearch, QueryCluster).outerjoin(
        QueryCluster, UnmatchedSearch.id == QueryCluster.id
    )
    if status == "open":
        query = query.filter(or_(QueryCluster.status == None, QueryCluster.status == "open"))
    elif status:
        query = query.filter(QueryCluster.status == status)
        
    queries = (
        query
        .order_by(desc(UnmatchedSearch.timestamp))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": q.UnmatchedSearch.id,
            "query_text": q.UnmatchedSearch.query_text,
            "timestamp": q.UnmatchedSearch.timestamp.isoformat(),
            "resolved_by_document_id": q.QueryCluster.resolved_by_document_id if q.QueryCluster else None,
            "resolved_at": q.QueryCluster.resolved_at.isoformat() if q.QueryCluster and q.QueryCluster.resolved_at else None,
        }
        for q in queries
    ]


@router.get("/frequent")
def get_frequent_queries(
    limit: int = Query(10, ge=1, le=100),
    status: str = Query("open"),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get the most frequent unanswered queries.
    """
    query = session.query(
        UnmatchedSearch.query_text,
        func.count(UnmatchedSearch.id).label("count")
    ).outerjoin(QueryCluster, UnmatchedSearch.id == QueryCluster.id)

    if status == "open":
        query = query.filter(or_(QueryCluster.status == None, QueryCluster.status == "open"))
    elif status:
        query = query.filter(QueryCluster.status == status)

    queries = (
        query
        .group_by(UnmatchedSearch.query_text)
        .order_by(desc("count"))
        .limit(limit)
        .all()
    )
    
    # Compute similarity matrix for the retrieved frequent queries
    if queries:
        query_texts = [q.query_text for q in queries]
        matrix = compute_query_similarity_matrix(query_texts)
        logger.info("Computed similarity matrix for %d frequent queries", len(query_texts))
        
    return [
        {
            "query_text": q.query_text,
            "count": q.count,
        }
        for q in queries
    ]


class Timeframe(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None

class ClusteredQueryResponse(BaseModel):
    id: int
    canonical_query: str
    volume_count: int
    timeframe: Timeframe
    resolved_by_document_id: Optional[int] = None
    resolved_at: Optional[datetime] = None

@router.get("/clustered", response_model=List[ClusteredQueryResponse])
def get_clustered_queries(
    start: str | None = Query(None, description="Start date (ISO format)"),
    end: str | None = Query(None, description="End date (ISO format)"),
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    status: str = Query("open"),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get unmatched queries clustered by similarity.
    """
    start_dt = None
    end_dt = None
    
    if start:
        start_dt = datetime.fromisoformat(start)
    if end:
        end_dt = datetime.fromisoformat(end)
        
    from app.services.query_clustering import cluster_unmatched_queries
    
    clusters = cluster_unmatched_queries(session, start_dt, end_dt, threshold, status)
    
    timeframe = Timeframe(start=start, end=end)
    
    return [
        ClusteredQueryResponse(
            id=c["id"],
            canonical_query=c["canonical_query"],
            volume_count=c["count"],
            timeframe=timeframe,
            resolved_by_document_id=c.get("resolved_by_document_id"),
            resolved_at=c.get("resolved_at")
        )
        for c in clusters
    ]

class MarkClusterHandledRequest(BaseModel):
    document_id: int

@router.patch("/clusters/{cluster_id}")
def mark_cluster(
    cluster_id: int,
    payload: MarkClusterHandledRequest,
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from app.services.document_service import get_user_document
    from fastapi import HTTPException
    
    doc = get_user_document(session, payload.document_id, user["username"])
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    from app.services.query_clustering import mark_cluster_handled
    cluster = mark_cluster_handled(session, cluster_id, payload.document_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
        
    return {"message": "Cluster marked as handled", "cluster_id": cluster.id, "status": cluster.status, "document_id": cluster.resolved_by_document_id}

