from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models import Base
from app.services import auth_service


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def test_passwords_are_hashed_with_argon2(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    assert user.password_hash.startswith("$argon2")
    assert "correct horse" not in user.password_hash


def test_register_rejects_duplicate_username(session):
    auth_service.register_user(session, "alice", "correct horse")
    with pytest.raises(auth_service.UsernameTakenError):
        auth_service.register_user(session, "alice", "another password")


def test_authenticate(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    assert auth_service.authenticate(session, "alice", "correct horse").id == user.id
    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.authenticate(session, "alice", "wrong")
    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.authenticate(session, "nobody", "correct horse")


def test_unusable_password_hash_never_verifies(session):
    # The ownership migration creates a placeholder owner with hash "!".
    assert auth_service.verify_password("!", "") is False
    assert auth_service.verify_password("!", "!") is False


def test_change_password(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.change_password(session, user, "wrong", "new password")
    auth_service.change_password(session, user, "correct horse", "new password")
    assert auth_service.authenticate(session, "alice", "new password").id == user.id


def test_token_round_trip(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    token = auth_service.create_access_token(user)
    assert auth_service.get_user_from_token(session, token).id == user.id


def test_expired_token_is_rejected(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    issued = datetime.now(timezone.utc) - timedelta(minutes=settings.access_token_ttl_minutes + 1)
    token = auth_service.create_access_token(user, now=issued)
    with pytest.raises(auth_service.InvalidTokenError):
        auth_service.get_user_from_token(session, token)


def test_token_signed_with_another_secret_is_rejected(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    forged = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "some-other-secret-value-that-is-long-enough",
        algorithm="HS256",
    )
    with pytest.raises(auth_service.InvalidTokenError):
        auth_service.get_user_from_token(session, forged)


def test_unsigned_token_is_rejected(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    unsigned = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        key=None,
        algorithm="none",
    )
    with pytest.raises(auth_service.InvalidTokenError):
        auth_service.get_user_from_token(session, unsigned)


def test_token_for_deleted_user_is_rejected(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    token = auth_service.create_access_token(user)
    session.delete(user)
    session.flush()
    with pytest.raises(auth_service.InvalidTokenError):
        auth_service.get_user_from_token(session, token)


def test_changing_the_password_invalidates_earlier_tokens(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    before = auth_service.create_access_token(user)
    auth_service.change_password(session, user, "correct horse", "new password")
    with pytest.raises(auth_service.InvalidTokenError):
        auth_service.get_user_from_token(session, before)
    after = auth_service.create_access_token(user)
    assert auth_service.get_user_from_token(session, after).id == user.id


def test_tokens_without_a_version_work_until_the_first_password_change(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    now = datetime.now(timezone.utc)
    legacy = jwt.encode(
        {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=5)},
        settings.jwt_secret.get_secret_value(), algorithm="HS256",
    )
    assert auth_service.get_user_from_token(session, legacy).id == user.id
    auth_service.change_password(session, user, "correct horse", "new password")
    with pytest.raises(auth_service.InvalidTokenError):
        auth_service.get_user_from_token(session, legacy)


def test_token_subject_identifies_signed_unexpired_tokens_without_a_lookup(session):
    user = auth_service.register_user(session, "alice", "correct horse")
    assert auth_service.token_subject(auth_service.create_access_token(user)) == user.id
    expired = auth_service.create_access_token(user, now=datetime.now(timezone.utc) - timedelta(days=30))
    assert auth_service.token_subject(expired) is None
    assert auth_service.token_subject("garbage") is None
    forged = jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                        "some-other-secret-0123456789abcdefghij", algorithm="HS256")
    assert auth_service.token_subject(forged) is None
