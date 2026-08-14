from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.services.document_service import list_user_documents
from app.services.document_search import search_documents

router = APIRouter(tags=["search"])


@router.get("/api/documents/search")
def search_user_documents(
    q: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Keyword search across user's document titles and chunk contents.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search query must not be empty")

    docs = list_user_documents(session, user["username"])
    matches = search_documents(docs, q)

    return [
        {
            "document_id": match.document_id,
            "title": match.title,
            "score": match.score,
            "snippet": match.snippet,
        }
        for match in matches
    ]
