from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from .evaluation import Base


class UserSettings(Base):
    """Per-user preferences. A user without a row uses the defaults."""

    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # "local" (the server's own embedding model) or a provider name; documents
    # indexed from now on are embedded with this provider's key.
    embedding_provider = Column(String(100), nullable=False, default="local")
    embedding_model = Column(String(255), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


__all__ = ["UserSettings"]
