from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models import ProviderKey
from app.services.provider_key import (
    encrypt_key,
    decrypt_key,
    save_provider_key,
    list_provider_keys,
    delete_provider_key,
    mask_key,
)
from app.services.provider_validation import verify_provider_key

router = APIRouter()

# Alias for backward compatibility
get_db_session = get_db


class ProviderKeyIn(BaseModel):
    provider: str
    key: str


class ProviderKeyOut(BaseModel):
    id: int
    provider: str
    masked_key: str

    @staticmethod
    def mask_key(key: str) -> str:
        """Mask the key for display (e.g., 'sk-***')."""
        return mask_key(key)


@router.post("/provider-keys")
def create_provider_key(
    payload: ProviderKeyIn,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not payload.provider or not payload.key:
        raise HTTPException(status_code=400, detail="provider and key required")
    if not verify_provider_key(payload.provider, payload.key):
        raise HTTPException(status_code=400, detail="invalid provider key")
    encrypted = encrypt_key(payload.key)
    pk = save_provider_key(session, payload.provider, encrypted)
    session.commit()
    return {"id": pk.id, "provider": pk.provider}


@router.get("/provider-keys", response_model=list)
def get_provider_keys(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """List all provider keys with masked values."""
    keys = list_provider_keys(session)
    result = []
    for pk in keys:
        try:
            plain = decrypt_key(pk.encrypted_key)
            masked = mask_key(plain)
        except Exception:
            masked = mask_key(pk.encrypted_key)
        result.append({"id": pk.id, "provider": pk.provider, "masked_key": masked})
    return result


@router.delete("/provider-keys/{key_id}")
def delete_provider_key_endpoint(
    key_id: int,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Delete a specific provider key by ID."""
    success = delete_provider_key(session, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Provider key not found")
    session.commit()
    return {"detail": "Provider key deleted"}
