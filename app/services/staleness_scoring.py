from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.services import usage_analytics, feedback_service
from app.models.document import DocumentRetrievalLog, SearchQueryLog

def compute_staleness_score(db: Session, document) -> float:
    score = 0.0
    
    last_reviewed = getattr(document, "last_reviewed_at", None)
    if not last_reviewed:
        score += 100.0
    else:
        dt = last_reviewed
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
            
        days_since_review = (datetime.now(timezone.utc) - dt).days
        score += max(0, days_since_review) * 2.0
        
    if db is not None:
        doc_id = getattr(document, "id", None)
        if doc_id is not None:
            # Usage penalty
            popular_docs = usage_analytics.get_popular_documents(db, limit=1000)
            for doc_stat in popular_docs:
                if doc_stat["document_id"] == doc_id:
                    score += doc_stat["count"] * 5.0
                    break
                    
            # Feedback penalty
            top_neg_queries = feedback_service.get_top_negative_feedback_queries(db, limit=1000)
            neg_query_texts = [item["query_text"] for item in top_neg_queries]
            if neg_query_texts:
                retrieval_count = (
                    db.query(DocumentRetrievalLog)
                    .join(SearchQueryLog)
                    .filter(
                        DocumentRetrievalLog.document_id == doc_id,
                        SearchQueryLog.query_text.in_(neg_query_texts)
                    )
                    .count()
                )
                score += retrieval_count * 10.0
            
    return float(score)
