from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

from .evaluation import Base as _Base

# Reuse existing Base from evaluation module
Base = _Base

class ProviderKey(Base):
    __tablename__ = "provider_keys"
    id = Column(Integer, primary_key=True)
    provider = Column(String(100), nullable=False)
    encrypted_key = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

__all__ = ["ProviderKey"]
