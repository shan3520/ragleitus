from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Boolean, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship

from .evaluation import Base

class SearchFeedback(Base):
    __tablename__ = "search_feedback"

    id = Column(Integer, primary_key=True)
    search_log_id = Column(Integer, ForeignKey("search_query_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    is_positive = Column(Boolean, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    search_log = relationship("SearchQueryLog")
