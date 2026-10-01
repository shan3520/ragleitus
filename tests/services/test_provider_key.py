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
    get_decrypted_key,
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

    pk = save_provider_key(session, 1, "openai", "enc_key_123")
    session.commit()
    assert pk.id is not None
    assert pk.user_id == 1
    assert pk.provider == "openai"
    assert pk.encrypted_key == "enc_key_123"

    keys = list_provider_keys(session, 1)
    assert len(keys) == 1
    assert keys[0].id == pk.id

    # Another user's keys are neither listed nor deletable.
    assert list_provider_keys(session, 2) == []
    assert delete_provider_key(session, 2, pk.id) is False

    deleted = delete_provider_key(session, 1, pk.id)
    session.commit()
    assert deleted is True
    assert list_provider_keys(session, 1) == []

    assert delete_provider_key(session, 1, 999) is False


def test_save_provider_key_replaces_existing_key_for_same_provider():
    session = _setup_in_memory_db()

    first = save_provider_key(session, 1, "openai", "enc_old")
    second = save_provider_key(session, 1, "openai", "enc_new")
    session.commit()

    assert first.id == second.id
    assert [k.encrypted_key for k in list_provider_keys(session, 1)] == ["enc_new"]


def test_get_decrypted_key_round_trips_and_is_scoped_to_user():
    session = _setup_in_memory_db()
    save_provider_key(session, 1, "groq", encrypt_key("gsk_secret_value"))
    session.commit()

    assert get_decrypted_key(session, 1, "groq") == "gsk_secret_value"
    assert get_decrypted_key(session, 2, "groq") is None
    assert get_decrypted_key(session, 1, "openai") is None


def test_mask_key_keeps_only_prefix_and_suffix_of_long_keys():
    masked = mask_key("sk-proj-abcdefghijklmnop1234")
    assert masked == "sk-***1234"
    assert "abcdefghijklmnop" not in masked
