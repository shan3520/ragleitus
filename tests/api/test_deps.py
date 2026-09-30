from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.deps import get_current_user, get_provider_factory
from app.db.database import SessionLocal
from app.services import auth_service
from app.services.llm import create_provider
from tests.helpers import unique_username


@pytest.fixture
def session():
    db = SessionLocal()
    yield db
    db.rollback()
    db.close()


def _user(session):
    user = auth_service.register_user(session, unique_username("deps"), "password123")
    session.flush()
    return user


def test_valid_bearer_token_resolves_to_the_user(session):
    user = _user(session)
    token = auth_service.create_access_token(user)
    assert get_current_user(f"Bearer {token}", session).id == user.id
    # The scheme is case-insensitive and surrounding whitespace is tolerated.
    assert get_current_user(f"bearer  {token} ", session).id == user.id


@pytest.mark.parametrize("header", [None, "", "Bearer", "Basic abc", "Token xyz", "Bearer not-a-jwt"])
def test_missing_or_malformed_headers_are_401(session, header):
    with pytest.raises(HTTPException) as exc:
        get_current_user(header, session)
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


def test_expired_token_is_401(session):
    user = _user(session)
    token = auth_service.create_access_token(user, now=datetime.now(timezone.utc) - timedelta(days=30))
    with pytest.raises(HTTPException) as exc:
        get_current_user(f"Bearer {token}", session)
    assert exc.value.detail == "Invalid or expired token"


def test_provider_factory_defaults_to_the_real_registry():
    assert get_provider_factory() is create_provider
