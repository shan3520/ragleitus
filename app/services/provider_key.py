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
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_key(plain: str, secret: Optional[str] = None) -> str:
    """
    Encrypt the provided key using Fernet symmetric encryption.
    """
    secret = secret or os.environ.get(SECRET_ENV, "dev-secret")
    if not _HAS_FERNET:
        raise RuntimeError("cryptography package is required for provider key encryption")
    key = _derive_fernet_key(secret)
    f = Fernet(key)
    token = f.encrypt(plain.encode())
    return token.decode()


def decrypt_key(ciphertext: str, secret: Optional[str] = None) -> str:
    """
    Decrypt an encrypted provider key back to plaintext.
    """
    secret = secret or os.environ.get(SECRET_ENV, "dev-secret")
    if not _HAS_FERNET:
        raise RuntimeError("cryptography package is required for provider key decryption")
    key = _derive_fernet_key(secret)
    f = Fernet(key)
    plain_bytes = f.decrypt(ciphertext.encode())
    return plain_bytes.decode()


def mask_key(plain_key: str) -> str:
    """
    Mask a provider key for display (e.g., 'sk-***').
    """
    if len(plain_key) > 3:
        return plain_key[:3] + "***"
    return "***"


def save_provider_key(session, provider: str, encrypted: str):
    """Save a provider key entity to the database session."""
    pk = ProviderKey(provider=provider, encrypted_key=encrypted)
    session.add(pk)
    session.flush()
    session.refresh(pk)
    return pk


def list_provider_keys(session):
    """List all provider keys from the database."""
    return session.query(ProviderKey).all()


def delete_provider_key(session, key_id: int):
    """Delete a provider key by ID from the database session."""
    pk = session.query(ProviderKey).filter_by(id=key_id).first()
    if pk:
        session.delete(pk)
        session.flush()
        return True
    return False
