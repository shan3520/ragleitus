from datetime import datetime, timezone
from sqlalchemy import Column, Float, Integer, String, ForeignKey, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from .evaluation import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True, index=True)
    title = Column(String(255), nullable=False)
    sha256 = Column(String(64), nullable=True, index=True)
    content = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    last_reviewed_at = Column(DateTime, nullable=True)
    review_status = Column(String(50), nullable=True)

    group = relationship("Group", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    feedbacks = relationship("SearchFeedback", secondary="document_feedback", back_populates="documents", cascade="all, delete")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    sequence_order = Column(Integer, nullable=False)

    document = relationship("Document", back_populates="chunks")


class UnmatchedSearch(Base):
    __tablename__ = "unmatched_searches"

    id = Column(Integer, primary_key=True)
    query_text = Column(String(255), nullable=False)
    duration_ms = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


__all__ = ["Document", "Chunk", "UnmatchedSearch", "SearchQueryLog", "DocumentRetrievalLog", "SavedSearch"]

class SearchQueryLog(Base):
    __tablename__ = "search_query_logs"

    id = Column(Integer, primary_key=True)
    query_text = Column(String(255), nullable=False, index=True)
    generated_answer = Column(Text, nullable=True)
    duration_ms = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    retrievals = relationship("DocumentRetrievalLog", back_populates="query_log", cascade="all, delete-orphan")


class DocumentRetrievalLog(Base):
    __tablename__ = "document_retrieval_logs"

    id = Column(Integer, primary_key=True)
    query_log_id = Column(Integer, ForeignKey("search_query_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    opened_at = Column(DateTime(timezone=True), nullable=True)

    query_log = relationship("SearchQueryLog", back_populates="retrievals")
    document = relationship("Document")


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    search_name = Column(String(255), nullable=False)
    query_text = Column(String(255), nullable=False)
    applied_filters = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "search_name", name="uq_saved_searches_user_id_search_name"),
    )
