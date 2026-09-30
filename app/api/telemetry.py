from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services import telemetry

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class TelemetryEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int | None
    message_id: int | None
    operation: str
    provider: str
    model: str
    status: str
    error_type: str | None
    latency_ms: float | None
    ttft_ms: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    tokens_estimated: bool
    cost_usd: float | None
    created_at: datetime


class TelemetryEventsPage(BaseModel):
    items: list[TelemetryEventOut]
    total: int


@router.get("/summary")
def telemetry_summary(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Latency, token usage, cost and error rate of your LLM calls, overall, per model and per day."""
    return telemetry.summarize(session, user.id, days)


@router.get("/events", response_model=TelemetryEventsPage)
def telemetry_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    items, total = telemetry.list_events(session, user.id, limit, offset)
    return {"items": items, "total": total}
