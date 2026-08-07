import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ProviderKey
from app.services.provider_key import encrypt_key, save_provider_key, list_provider_keys, delete_provider_key
from app.services.provider_validation import verify_provider_key

router = APIRouter()

class ProviderKeyIn(BaseModel):
    provider: str
    key: str


class ProviderKeyOut(BaseModel):
    id: int
    provider: str
    masked_key: str

    @staticmethod
    def mask_key(encrypted_key: str) -> str:
        """Mask the encrypted key for display (e.g., 'sk-***')."""
        if len(encrypted_key) > 3:
            return encrypted_key[:3] + "***"
        return "***"


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


@router.get("/provider-keys", response_model=list)
def get_provider_keys(session=Depends(get_db_session)):
    """List all provider keys with masked values."""
    keys = list_provider_keys(session)
    return [
        {
            "id": pk.id,
            "provider": pk.provider,
            "masked_key": ProviderKeyOut.mask_key(pk.encrypted_key)
        }
        for pk in keys
    ]


@router.delete("/provider-keys/{key_id}")
def delete_provider_key_endpoint(key_id: int, session=Depends(get_db_session)):
    """Delete a specific provider key by ID."""
    success = delete_provider_key(session, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Provider key not found")
    return {"detail": "Provider key deleted"}
