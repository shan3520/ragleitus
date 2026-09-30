from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, text

from .evaluation import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(150), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    # Copied into every access token; bumping it (on a password change) invalidates all earlier tokens.
    token_version = Column(Integer, nullable=False, default=0, server_default=text("0"))


__all__ = ["User"]
