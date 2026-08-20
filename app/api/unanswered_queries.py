from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.db.database import get_db
from app.models.document import UnmatchedSearch
from app.api.auth import get_current_user
from app.services.query_similarity import compute_query_similarity_matrix
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/unanswered-queries", tags=["analytics"])


@router.get("/recent")
def get_recent_queries(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get recent unanswered queries, paginated.
    """
    queries = (
        session.query(UnmatchedSearch)
        .order_by(desc(UnmatchedSearch.timestamp))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": q.id,
            "query_text": q.query_text,
            "timestamp": q.timestamp.isoformat(),
        }
        for q in queries
    ]


@router.get("/frequent")
def get_frequent_queries(
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get the most frequent unanswered queries.
    """
    queries = (
        session.query(
            UnmatchedSearch.query_text,
            func.count(UnmatchedSearch.id).label("count")
        )
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


@router.get("/clustered")
def get_clustered_queries(
    start: str | None = Query(None, description="Start date (ISO format)"),
    end: str | None = Query(None, description="End date (ISO format)"),
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get unmatched queries clustered by similarity.
    """
    from datetime import datetime
    
    start_dt = None
    end_dt = None
    
    if start:
        start_dt = datetime.fromisoformat(start)
    if end:
        end_dt = datetime.fromisoformat(end)
        
    from app.services.query_clustering import cluster_unmatched_queries
    
    clusters = cluster_unmatched_queries(session, start_dt, end_dt, threshold)
    
    # We might not want to return the full list of queries in the cluster to keep response clean,
    # but the task didn't specify exactly. I'll include canonical_query and count.
    return [
        {
            "canonical_query": c["canonical_query"],
            "count": c["count"],
            "queries": c["queries"],
        }
        for c in clusters
    ]
