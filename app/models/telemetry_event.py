from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String

from .evaluation import Base


class TelemetryEvent(Base):
    """One LLM call: who made it, against which provider and model, how long it
    took, how many tokens it used and what it cost."""

    __tablename__ = "telemetry_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, nullable=True, index=True)
    message_id = Column(Integer, nullable=True)
    operation = Column(String(50), nullable=False)  # "chat", "evaluation"
    provider = Column(String(100), nullable=False)
    model = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False)  # "ok" or "error"
    error_type = Column(String(100), nullable=True)
    latency_ms = Column(Float, nullable=True)
    ttft_ms = Column(Float, nullable=True)  # time to first token, streamed calls only
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    # True when token counts were estimated because the provider did not report usage.
    tokens_estimated = Column(Boolean, nullable=False, default=False)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


__all__ = ["TelemetryEvent"]
