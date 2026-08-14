import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.evaluation import Base
from app.services.provider_key import (
    encrypt_key,
    decrypt_key,
    mask_key,
    save_provider_key,
    list_provider_keys,
    delete_provider_key,
)


def _setup_in_memory_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_encrypt_and_decrypt_key():
    secret = "custom-test-secret"
    plain = "sk-proj-test1234567890"

    encrypted = encrypt_key(plain, secret=secret)
    assert encrypted != plain
    assert len(encrypted) > 0

    decrypted = decrypt_key(encrypted, secret=secret)
    assert decrypted == plain


def test_mask_key():
    assert mask_key("sk-123456") == "sk-***"
    assert mask_key("abc") == "***"
    assert mask_key("a") == "***"


def test_provider_key_service_crud():
    session = _setup_in_memory_db()

    # Save
    pk = save_provider_key(session, "openai", "enc_key_123")
    session.commit()
    assert pk.id is not None
    assert pk.provider == "openai"
    assert pk.encrypted_key == "enc_key_123"

    # List
    keys = list_provider_keys(session)
    assert len(keys) == 1
    assert keys[0].id == pk.id

    # Delete
    deleted = delete_provider_key(session, pk.id)
    session.commit()
    assert deleted is True

    keys_after = list_provider_keys(session)
    assert len(keys_after) == 0

    # Delete non-existent
    deleted_nonexistent = delete_provider_key(session, 999)
    assert deleted_nonexistent is False
