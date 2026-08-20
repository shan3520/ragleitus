from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .evaluation import Base

class QueryCluster(Base):
    __tablename__ = "query_clusters"

    id = Column(Integer, primary_key=True)
    status = Column(String(50), nullable=True)
    resolved_by_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

__all__ = ["QueryCluster"]
