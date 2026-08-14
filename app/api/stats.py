from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.services.document_service import list_user_documents
from app.services.document_stats import compute_document_stats

router = APIRouter(tags=["stats"])


@router.get("/api/documents/stats")
def get_collection_stats(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Get aggregate document collection statistics for the current user.
    """
    documents = list_user_documents(session, user["username"])
    stats = compute_document_stats(documents)
    return {
        "total_documents": stats.total_documents,
        "total_chunks": stats.total_chunks,
        "avg_chunks_per_document": stats.avg_chunks_per_document,
        "status_counts": stats.status_counts,
        "total_content_length": stats.total_content_length,
    }
