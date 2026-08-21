from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.document import DocumentRetrievalLog
from app.services.document_service import list_user_documents
from app.services.document_search import search_documents

router = APIRouter(tags=["search"])


@router.get("/api/documents/search")
def search_user_documents(
    q: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Keyword search across user's document titles and chunk contents.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search query must not be empty")

    docs = list_user_documents(session, user["username"])
    matches = search_documents(docs, q, background_tasks=background_tasks, session=session)

    return [
        {
            "document_id": match.document_id,
            "title": match.title,
            "score": match.score,
            "snippet": match.snippet,
        }
        for match in matches
    ]


@router.post("/api/documents/search/{search_id}/documents/{document_id}/open")
def log_document_open(search_id: int, document_id: int, db: Session = Depends(get_db)):
    """
    Record the timestamp at which the user opened a retrieved document.
    """
    retrieval_log = (
        db.query(DocumentRetrievalLog)
        .filter(
            DocumentRetrievalLog.query_log_id == search_id,
            DocumentRetrievalLog.document_id == document_id,
        )
        .first()
    )
    if retrieval_log is None:
        raise HTTPException(status_code=404, detail="Document retrieval log not found")

    retrieval_log.opened_at = func.now()
    db.commit()
    return {"status": "ok"}
