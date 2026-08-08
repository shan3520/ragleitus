from sqlalchemy import Column, Integer, String

from .evaluation import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(255), nullable=False)


__all__ = ["Document"]
