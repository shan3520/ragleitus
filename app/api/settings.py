"""Per-user settings: which embedding model new documents are embedded with."""
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services import embedding_service, ingestion

router = APIRouter(prefix="/api/settings", tags=["settings"])


class EmbeddingSettingsUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=100, description='"local" or a provider you have a key for')
    model: str | None = Field(default=None, max_length=255, description="Embedding model; the provider's default if omitted")


class ReindexRequest(BaseModel):
    scope: Literal["outdated", "all"] = "outdated"


@router.get("/embeddings")
def get_embedding_settings(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Your embedding choice, the choices available, and how many documents use each model."""
    return embedding_service.describe(session, user.id)


@router.put("/embeddings")
def update_embedding_settings(
    payload: EmbeddingSettingsUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Embed documents indexed from now on with this provider and model.

    The choice is checked by embedding a short text with your key first.
    Existing documents keep their vectors until re-indexed (see /reindex).
    """
    try:
        embedding_service.save_choice(session, user.id, payload.provider, payload.model)
    except embedding_service.EmbeddingSettingsError as exc:
        session.commit()  # keep the telemetry of the check
        raise HTTPException(status_code=400, detail=str(exc))
    session.commit()
    return embedding_service.describe(session, user.id)


@router.post("/embeddings/reindex", status_code=202)
def reindex_for_embeddings(
    background_tasks: BackgroundTasks,
    payload: ReindexRequest | None = Body(default=None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Re-index the documents not yet embedded with your current choice (or all of them)."""
    scope = payload.scope if payload else "outdated"
    if scope == "all":
        document_ids = ingestion.reindexable_document_ids(session, user.id)
    else:
        document_ids = embedding_service.outdated_document_ids(session, user.id)
    queued = ingestion.mark_documents_for_reindex(session, user.id, document_ids)
    session.commit()
    for document_id in queued:
        ingestion.schedule_indexing(document_id, background_tasks)
    return {"queued": len(queued), "document_ids": queued}
