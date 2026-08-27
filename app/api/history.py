from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.api.auth import get_current_user
from app.services.audit_service import get_audit_logs

router = APIRouter(prefix="/api/history", tags=["history"])


class AuditLogResponse(BaseModel):
    id: int
    action: str
    document_id: Optional[int] = None
    timestamp: datetime


class HistoryResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int


@router.get("", response_model=HistoryResponse)
def get_history(
    entity_id: Optional[int] = Query(None),
    entity_type: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    logs, total = get_audit_logs(
        session,
        entity_id=entity_id,
        entity_type=entity_type,
        action_type=action_type,
        limit=limit,
        offset=offset,
    )
    return {"items": logs, "total": total}
