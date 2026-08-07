import os
import base64
import hashlib
from typing import Optional

try:
    from cryptography.fernet import Fernet
    _HAS_FERNET = True
except Exception:
    _HAS_FERNET = False

from app.models.provider_key import ProviderKey

SECRET_ENV = "PROVIDER_KEY_SECRET"


def _derive_fernet_key(secret: str) -> bytes:
    # Derive a 32-byte key and urlsafe-base64 encode it for Fernet
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_key(plain: str, secret: Optional[str] = None) -> str:
    """
    Encrypt the provided key using Fernet if available. Falls back to a deterministic
    base64-encoded sha256 HMAC-like string if cryptography isn't installed.
    """
    secret = secret or os.environ.get(SECRET_ENV, "dev-secret")
    if _HAS_FERNET:
        key = _derive_fernet_key(secret)
        f = Fernet(key)
        token = f.encrypt(plain.encode())
        return token.decode()
    else:
        # Fallback: not true encryption but obfuscation using sha256 + secret
        blob = hashlib.sha256((secret + plain).encode()).digest()
        return base64.urlsafe_b64encode(blob).decode()


def save_provider_key(session, provider: str, encrypted: str):
    pk = ProviderKey(provider=provider, encrypted_key=encrypted)
    session.add(pk)
    session.commit()
    session.refresh(pk)
    return pk


def list_provider_keys(session):
    """List all provider keys from the database."""
    return session.query(ProviderKey).all()


def delete_provider_key(session, key_id: int):
    """Delete a provider key by ID."""
    pk = session.query(ProviderKey).filter_by(id=key_id).first()
    if pk:
        session.delete(pk)
        session.commit()
        return True
    return False
