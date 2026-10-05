from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .evaluation import Base


def _now():
    return datetime.now(timezone.utc)


class Prompt(Base):
    """A named system prompt in a user's prompt library; its text lives in versions."""

    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    # Prompts created before ownership existed have none and are shown to nobody.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=True)

    versions = relationship(
        "PromptVersion", back_populates="prompt", cascade="all, delete-orphan", order_by="PromptVersion.version"
    )


class PromptVersion(Base):
    """One saved text of a prompt. Versions are never edited, only added."""

    __tablename__ = "prompt_versions"

    id = Column(Integer, primary_key=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    # The system prompt; {context} is replaced by the numbered passages and
    # {question} (optional) by the question.
    template = Column(Text, nullable=False)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    prompt = relationship("Prompt", back_populates="versions")

    __table_args__ = (UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_id_version"),)


__all__ = ["Prompt", "PromptVersion"]
