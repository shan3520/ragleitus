from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.models.feedback import SearchFeedback
from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document

def create_feedback(db: Session, search_log_id: int, is_positive: bool, comment: str = None) -> SearchFeedback:
    feedback = SearchFeedback(
        search_log_id=search_log_id,
        is_positive=is_positive,
        comment=comment
    )
    
    retrievals = db.query(DocumentRetrievalLog).filter(DocumentRetrievalLog.query_log_id == search_log_id).all()
    for r in retrievals:
        if r.document:
            feedback.documents.append(r.document)
            
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback

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

def get_top_negative_feedback_queries(db: Session, limit: int = 10):
    results = (
        db.query(
            SearchQueryLog.query_text,
            func.count(SearchFeedback.id).label("negative_count")
        )
        .join(SearchFeedback, SearchFeedback.search_log_id == SearchQueryLog.id)
        .filter(SearchFeedback.is_positive == False)
        .group_by(SearchQueryLog.query_text)
        .order_by(desc("negative_count"))
        .limit(limit)
        .all()
    )
    
    return [
        {
            "query_text": r.query_text,
            "count": r.negative_count
        }
        for r in results
    ]

def calculate_document_negative_impact(db: Session, document_id: int) -> float:
    count = (
        db.query(func.count(SearchFeedback.id))
        .join(SearchFeedback.documents)
        .filter(Document.id == document_id)
        .filter(SearchFeedback.is_positive == False)
        .scalar()
    )
    
    return float(count or 0)
