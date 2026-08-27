from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String

from .evaluation import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    action = Column(String(100), nullable=False)
    document_id = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


__all__ = ["AuditLog"]