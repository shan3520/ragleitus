from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_provider_factory
from app.db.database import get_db
from app.models.user import User
from app.services.llm import PROVIDERS, ProviderFactory, UnknownProviderError, get_spec
from app.services.provider_key import (
    decrypt_key,
    delete_provider_key,
    encrypt_key,
    get_provider_key,
    list_provider_keys,
    masked_value,
    save_provider_key,
)
from app.services.provider_validation import verify_provider_key

router = APIRouter(tags=["providers"])


class ProviderOut(BaseModel):
    name: str
    label: str
    default_model: str
    requires_base_url: bool
    configured: bool


class ProviderKeyIn(BaseModel):
    provider: str
    key: str = Field(min_length=1, max_length=1000)
    base_url: HttpUrl | None = None
    validate_key: bool = Field(default=True, alias="validate")


class ProviderKeyOut(BaseModel):
    id: int
    provider: str
    masked_key: str
    base_url: str | None = None


class ValidationOut(BaseModel):
    valid: bool
    detail: str


def _out(pk) -> dict:
    return {"id": pk.id, "provider": pk.provider, "masked_key": masked_value(pk), "base_url": pk.base_url}


@router.get("/api/providers", response_model=list[ProviderOut])
def list_providers(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Supported LLM providers, and whether the current user has a key stored for each.

    A provider that is not offered for new keys (see ProviderSpec.unavailable)
    is listed only to users who already have its key.
    """
    configured = {pk.provider for pk in list_provider_keys(session, user.id)}
    return [
        ProviderOut(
            name=spec.name,
            label=spec.label,
            default_model=spec.default_model,
            requires_base_url=spec.requires_base_url,
            configured=spec.name in configured,
        )
        for spec in PROVIDERS.values()
        if spec.offered or spec.name in configured
    ]


@router.post("/api/provider-keys", response_model=ProviderKeyOut)
@router.post("/provider-keys", response_model=ProviderKeyOut, include_in_schema=False)
async def create_provider_key(
    payload: ProviderKeyIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    factory: ProviderFactory = Depends(get_provider_factory),
):
    """Store (or replace) the user's key for a provider.

    The key is checked against the provider before it is saved unless
    `validate` is false. It is encrypted at rest and only ever returned masked.
    """
    try:
        spec = get_spec(payload.provider)
    except UnknownProviderError:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{payload.provider}'")
    if not spec.offered and get_provider_key(session, user.id, spec.name) is None:
        raise HTTPException(status_code=400, detail=spec.unavailable)
    base_url = str(payload.base_url).rstrip("/") if payload.base_url else None
    if spec.requires_base_url and not base_url:
        raise HTTPException(status_code=400, detail=f"{spec.label} needs a base_url")
    if not spec.requires_base_url:
        base_url = None

    if payload.validate_key:
        check = await verify_provider_key(spec.name, payload.key, base_url, factory=factory)
        if not check.valid:
            raise HTTPException(status_code=502 if check.unreachable else 400, detail=check.detail)

    pk = save_provider_key(session, user.id, spec.name, encrypt_key(payload.key), base_url)
    session.commit()
    return _out(pk)


@router.get("/api/provider-keys", response_model=list[ProviderKeyOut])
@router.get("/provider-keys", response_model=list[ProviderKeyOut], include_in_schema=False)
def get_provider_keys(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """List the user's provider keys with masked values."""
    return [_out(pk) for pk in list_provider_keys(session, user.id)]


@router.post("/api/provider-keys/{provider}/validate", response_model=ValidationOut)
async def validate_stored_key(
    provider: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    factory: ProviderFactory = Depends(get_provider_factory),
):
    """Check that the user's stored key for a provider still works."""
    pk = get_provider_key(session, user.id, provider)
    if pk is None:
        raise HTTPException(status_code=404, detail="Provider key not found")
    check = await verify_provider_key(provider, decrypt_key(pk.encrypted_key), pk.base_url, factory=factory)
    return ValidationOut(valid=check.valid, detail=check.detail)


@router.delete("/api/provider-keys/{key_id}")
@router.delete("/provider-keys/{key_id}", include_in_schema=False)
def delete_provider_key_endpoint(
    key_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Delete a specific provider key by ID."""
    if not delete_provider_key(session, user.id, key_id):
        raise HTTPException(status_code=404, detail="Provider key not found")
    session.commit()
    return {"detail": "Provider key deleted"}
