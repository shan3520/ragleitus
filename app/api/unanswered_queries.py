from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.db.database import get_db
from app.models.document import UnmatchedSearch
from app.api.auth import get_current_user

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
    return [
        {
            "query_text": q.query_text,
            "count": q.count,
        }
        for q in queries
    ]
