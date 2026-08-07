import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ProviderKey
from app.services.provider_key import encrypt_key, save_provider_key
from app.services.provider_validation import verify_provider_key

router = APIRouter()

class ProviderKeyIn(BaseModel):
    provider: str
    key: str


def get_db_session():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./provider_keys.db")
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


@router.post("/provider-keys")
def create_provider_key(payload: ProviderKeyIn, session=Depends(get_db_session)):
    if not payload.provider or not payload.key:
        raise HTTPException(status_code=400, detail="provider and key required")
    if not verify_provider_key(payload.provider, payload.key):
        raise HTTPException(status_code=400, detail="invalid provider key")
    encrypted = encrypt_key(payload.key)
    pk = save_provider_key(session, payload.provider, encrypted)
    return {"id": pk.id, "provider": pk.provider}
