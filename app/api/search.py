from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.document import DocumentRetrievalLog, SavedSearch
from app.services.document_service import list_user_documents
from app.services.document_search import SearchMatch, search_documents_paginated

router = APIRouter(tags=["search"])


class PaginatedSearchResponse(BaseModel):
    total: int
    items: list[SearchMatch]


class SavedSearchUpsert(BaseModel):
    search_name: str
    query_text: str
    applied_filters: dict | None = None


class SavedSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    search_name: str
    query_text: str
    applied_filters: dict | None = None


@router.get("/api/documents/search", response_model=PaginatedSearchResponse)
def search_user_documents(
    q: str,
    background_tasks: BackgroundTasks,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Keyword search across user's document titles and chunk contents.

    Returns a paginated response: `total` counts all matching documents and
    `items` holds at most `limit` matches starting at `offset`.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search query must not be empty")

    docs = list_user_documents(session, user["username"])
    total_matches, matches = search_documents_paginated(
        docs,
        q,
        background_tasks=background_tasks,
        session=session,
        limit=limit,
        offset=offset,
    )

    return PaginatedSearchResponse(total=total_matches, items=list(matches))


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


@router.get("/api/documents/saved-searches", response_model=list[SavedSearchResponse])
def list_saved_searches(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    List the authenticated user's saved search configurations.
    """
    return (
        session.query(SavedSearch)
        .filter(SavedSearch.user_id == user["username"])
        .all()
    )


@router.get("/api/documents/saved-searches/{search_id}", response_model=SavedSearchResponse)
def get_saved_search(
    search_id: int,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Fetch a single saved search owned by the authenticated user.
    """
    saved_search = (
        session.query(SavedSearch)
        .filter(SavedSearch.id == search_id)
        .first()
    )
    if saved_search is None or saved_search.user_id != user["username"]:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return saved_search


@router.delete("/api/documents/saved-searches/{search_id}", status_code=204)
def delete_saved_search(
    search_id: int,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Delete a saved search owned by the authenticated user.
    """
    saved_search = (
        session.query(SavedSearch)
        .filter(SavedSearch.id == search_id)
        .first()
    )
    if saved_search is None or saved_search.user_id != user["username"]:
        raise HTTPException(status_code=404, detail="Saved search not found")
    session.delete(saved_search)
    session.commit()


@router.put("/api/documents/saved-searches", response_model=SavedSearchResponse)
def upsert_saved_search(
    payload: SavedSearchUpsert,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Create or update a named saved search configuration for the current user.
    """
    saved_search = (
        session.query(SavedSearch)
        .filter(
            SavedSearch.user_id == user["username"],
            SavedSearch.search_name == payload.search_name,
        )
        .first()
    )
    if saved_search is None:
        saved_search = SavedSearch(
            user_id=user["username"],
            search_name=payload.search_name,
        )
        session.add(saved_search)
    saved_search.query_text = payload.query_text
    saved_search.applied_filters = payload.applied_filters
    session.commit()
    session.refresh(saved_search)
    return saved_search
