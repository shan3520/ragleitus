"""Storage of users' LLM provider API keys (BYOK).

Keys are encrypted at rest with Fernet, keyed from `PROVIDER_KEY_SECRET`.
Plaintext keys only exist in memory while a request to the provider is being
made, and are never logged or returned by the API; responses carry the
masked form from `mask_key`.
"""

import base64
import hashlib

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.provider_key import ProviderKey


def _fernet(secret: str | None = None) -> Fernet:
    secret = secret or settings.provider_key_secret.get_secret_value()
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(plain: str, secret: str | None = None) -> str:
    return _fernet(secret).encrypt(plain.encode()).decode()


def decrypt_key(ciphertext: str, secret: str | None = None) -> str:
    return _fernet(secret).decrypt(ciphertext.encode()).decode()


def mask_key(plain_key: str) -> str:
    """Mask a provider key for display, keeping only a short prefix and suffix."""
    if len(plain_key) >= 12:
        return f"{plain_key[:3]}***{plain_key[-4:]}"
    if len(plain_key) > 3:
        return plain_key[:3] + "***"
    return "***"


def masked_value(pk: ProviderKey) -> str:
    try:
        return mask_key(decrypt_key(pk.encrypted_key))
    except Exception:
        return "***"


def save_provider_key(session: Session, user_id: int, provider: str, encrypted: str, base_url: str | None = None) -> ProviderKey:
    """Store the user's key for a provider, replacing any key they already had for it."""
    pk = get_provider_key(session, user_id, provider)
    if pk is None:
        pk = ProviderKey(user_id=user_id, provider=provider, encrypted_key=encrypted, base_url=base_url)
        session.add(pk)
    else:
        pk.encrypted_key = encrypted
        pk.base_url = base_url
    session.flush()
    session.refresh(pk)
    return pk


def get_provider_key(session: Session, user_id: int, provider: str) -> ProviderKey | None:
    return (
        session.query(ProviderKey)
        .filter(ProviderKey.user_id == user_id, ProviderKey.provider == provider)
        .first()
    )


def get_decrypted_key(session: Session, user_id: int, provider: str) -> str | None:
    """Return the user's plaintext key for a provider, or None if they have not stored one."""
    pk = get_provider_key(session, user_id, provider)
    return decrypt_key(pk.encrypted_key) if pk else None


class MissingProviderKeyError(Exception):
    """The user has not stored a key for the provider they asked to use."""


def create_user_provider(session: Session, user_id: int, provider: str, factory):
    """Build a chat provider authenticated with the user's own stored key."""
    pk = get_provider_key(session, user_id, provider)
    if pk is None:
        raise MissingProviderKeyError(provider)
    return factory(provider, decrypt_key(pk.encrypted_key), pk.base_url)


def list_provider_keys(session: Session, user_id: int) -> list[ProviderKey]:
    return (
        session.query(ProviderKey)
        .filter(ProviderKey.user_id == user_id)
        .order_by(ProviderKey.provider)
        .all()
    )


def delete_provider_key(session: Session, user_id: int, key_id: int) -> bool:
    pk = (
        session.query(ProviderKey)
        .filter(ProviderKey.id == key_id, ProviderKey.user_id == user_id)
        .first()
    )
    if pk:
        session.delete(pk)
        session.flush()
        return True
    return False
