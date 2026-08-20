from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.feedback import SearchFeedback
from app.models.document import SearchQueryLog

def get_recent_negative_feedback(db: Session, limit: int = 10):
    results = (
        db.query(
            SearchFeedback.id,
            SearchQueryLog.query_text,
            SearchQueryLog.generated_answer,
            SearchFeedback.comment,
            SearchFeedback.created_at
        )
        .join(SearchQueryLog, SearchFeedback.search_log_id == SearchQueryLog.id)
        .filter(SearchFeedback.is_positive == False)
        .order_by(desc(SearchFeedback.created_at))
        .limit(limit)
        .all()
    )
    
    return [
        {
            "id": r.id,
            "query_text": r.query_text,
            "generated_answer": r.generated_answer,
            "comment": r.comment,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ]
