from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.api.auth import get_current_user
from app.services.feedback_service import get_recent_negative_feedback

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

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
