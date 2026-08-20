from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from app.db.database import get_db
from app.api.auth import get_current_user
from app.services.feedback_service import get_recent_negative_feedback, get_top_negative_feedback_queries, create_feedback

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

class TopNegativeQueryResponse(BaseModel):
    query_text: str
    count: int

class FeedbackCreate(BaseModel):
    search_log_id: int
    is_positive: bool
    comment: str | None = None

@router.post("")
def submit_feedback(
    data: FeedbackCreate,
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Submit feedback for a search log and link retrieved documents.
    """
    fb = create_feedback(session, data.search_log_id, data.is_positive, data.comment)
    return {
        "id": fb.id,
        "search_log_id": fb.search_log_id,
        "is_positive": fb.is_positive,
        "comment": fb.comment,
        "documents": [doc.id for doc in fb.documents]
    }



@router.get("/negative")
def get_negative_feedback(
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Get recent negative feedback with the original query, generated answer, and user comment.
    """
    return get_recent_negative_feedback(session, limit)

@router.get("/top-negative-queries", response_model=List[TopNegativeQueryResponse])
def get_top_negative_feedback_queries_endpoint(
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Get top negative feedback queries sorted by their negative feedback counts.
    """
    return get_top_negative_feedback_queries(session, limit)
