from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime
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
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


__all__ = ["Document", "Chunk", "UnmatchedSearch", "SearchQueryLog", "DocumentRetrievalLog"]

class SearchQueryLog(Base):
    __tablename__ = "search_query_logs"

    id = Column(Integer, primary_key=True)
    query_text = Column(String(255), nullable=False, index=True)
    generated_answer = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    retrievals = relationship("DocumentRetrievalLog", back_populates="query_log", cascade="all, delete-orphan")


class DocumentRetrievalLog(Base):
    __tablename__ = "document_retrieval_logs"

    id = Column(Integer, primary_key=True)
    query_log_id = Column(Integer, ForeignKey("search_query_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    query_log = relationship("SearchQueryLog", back_populates="retrievals")
    document = relationship("Document")
