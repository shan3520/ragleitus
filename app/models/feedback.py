from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Boolean, ForeignKey, Text, DateTime, Table
from sqlalchemy.orm import relationship

from .evaluation import Base

document_feedback = Table(
    "document_feedback",
    Base.metadata,
    Column("search_feedback_id", Integer, ForeignKey("search_feedback.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
)

class SearchFeedback(Base):
    __tablename__ = "search_feedback"

    id = Column(Integer, primary_key=True)
    search_log_id = Column(Integer, ForeignKey("search_query_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    is_positive = Column(Boolean, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    search_log = relationship("SearchQueryLog")
    documents = relationship("Document", secondary=document_feedback, back_populates="feedbacks")
