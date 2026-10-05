from datetime import datetime, timezone
from sqlalchemy import Column, Float, Integer, String, ForeignKey, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from .evaluation import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=True)
    sha256 = Column(String(64), nullable=True, index=True)
    # Cleaned text, pages separated by a form feed (see app.services.ingestion).
    content = Column(Text, nullable=True)
    # pending -> indexing -> ready | failed
    status = Column(String(50), nullable=False, default="pending")
    error = Column(Text, nullable=True)
    # Identifies the index run that currently owns the document; a newer run
    # takes over and an older one then discards its work (see ingestion).
    index_token = Column(String(36), nullable=True)
    # When the document was last queued or claimed for indexing; used to find
    # documents whose run was lost.
    index_updated_at = Column(DateTime(timezone=True), nullable=True)
    # The embedding model the document's current vectors were made with, set
    # when indexing finishes: "local" (or NULL, for documents indexed before
    # this was recorded) means the server's own model; otherwise a provider
    # name, its model and the vector size, which together name the vector
    # collection (see embedding_service).
    embedding_provider = Column(String(100), nullable=True)
    embedding_model = Column(String(255), nullable=True)
    embedding_dimension = Column(Integer, nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    last_reviewed_at = Column(DateTime, nullable=True)
    review_status = Column(String(50), nullable=True)

    group = relationship("Group", back_populates="documents")
    # passive_deletes: the database removes chunks via ON DELETE CASCADE, so
    # deleting a document never works from a stale list of chunks (a re-index
    # may be replacing them at the same moment).
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan", passive_deletes=True)
    feedbacks = relationship("SearchFeedback", secondary="document_feedback", back_populates="documents", cascade="all, delete")


class Chunk(Base):
    __tablename__ = "chunks"
    # Chunk ids are also vector point ids, so they must never be reused: an index
    # run that is superseded removes the vectors of the chunks it created, and a
    # reused id would remove another run's vector. PostgreSQL sequences never
    # reuse ids; SQLite needs AUTOINCREMENT for the same guarantee.
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    sequence_order = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    token_count = Column(Integer, nullable=True)

    document = relationship("Document", back_populates="chunks")


class UnmatchedSearch(Base):
    __tablename__ = "unmatched_searches"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    query_text = Column(String(255), nullable=False)
    duration_ms = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


__all__ = ["Document", "Chunk", "UnmatchedSearch", "SearchQueryLog", "DocumentRetrievalLog", "SavedSearch"]

class SearchQueryLog(Base):
    __tablename__ = "search_query_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    search_name = Column(String(255), nullable=False)
    query_text = Column(String(255), nullable=False)
    applied_filters = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "search_name", name="uq_saved_searches_user_id_search_name"),
    )
