import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.auth import get_current_user
from app.models import Document

router = APIRouter()


def get_db_session():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./documents.db")
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@router.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user), session=Depends(get_db_session)):
    return [
        {"id": document.id, "user_id": document.user_id, "title": document.title}
        for document in session.query(Document).filter_by(user_id=user["username"]).all()
    ]
