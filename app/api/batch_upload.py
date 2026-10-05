"""Indexing status of a user's documents."""
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services import ingestion

router = APIRouter(tags=["batch"])


class BatchStatusRequest(BaseModel):
    document_ids: list[int] | None = Field(
        default=None, max_length=1000, description="Only these documents; all of yours if omitted"
    )


@router.post("/api/documents/batch-status")
def batch_status(
    request: BatchStatusRequest | None = Body(default=None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """How many of your documents are queued, indexing, ready or failed, with each one's status."""
    return ingestion.batch_status(session, user.id, request.document_ids if request else None)
