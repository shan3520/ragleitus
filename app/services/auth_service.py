"""User registration, password hashing and access tokens.

Passwords are hashed with argon2. Access tokens are HS256 JWTs whose subject
is the user's id; the signing secret comes from settings and is never logged.
"""

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User

_hasher = PasswordHasher()
_ALGORITHM = "HS256"


class UsernameTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def register_user(session: Session, username: str, password: str) -> User:
    if session.query(User).filter(User.username == username).first() is not None:
        raise UsernameTakenError(username)
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, username: str, password: str) -> User:
    user = session.query(User).filter(User.username == username).first()
    if user is None or not verify_password(user.password_hash, password):
        raise InvalidCredentialsError()
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        session.flush()
    return user


def change_password(session: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentialsError()
    user.password_hash = hash_password(new_password)
    # Sign out every existing session, e.g. one using a stolen token.
    user.token_version = (user.token_version or 0) + 1
    session.flush()


def create_access_token(user: User, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "ver": user.token_version or 0,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)


def _decode(token: str) -> tuple[int, dict]:
    """Verify signature and expiry; return (user_id, payload)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return int(payload["sub"]), payload
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def token_subject(token: str) -> int | None:
    """The user id of a token this server signed and that has not expired, without a database lookup.

    Enough to tell callers apart (e.g. for rate limiting); use
    get_user_from_token to authorize a request.
    """
    try:
        return _decode(token)[0]
    except InvalidTokenError:
        return None


def get_user_from_token(session: Session, token: str) -> User:
    user_id, payload = _decode(token)

    user = session.get(User, user_id)
    if user is None:
        raise InvalidTokenError("user not found")
    if payload.get("ver", 0) != (user.token_version or 0):
        raise InvalidTokenError("token was issued before the last password change")
    return user
