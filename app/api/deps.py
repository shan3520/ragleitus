"""Dependencies shared by route handlers."""

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.services.auth_service import InvalidTokenError, get_user_from_token


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_db),
) -> User:
    if not authorization:
        raise _unauthorized("Missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("Invalid authorization header")
    try:
        return get_user_from_token(session, token.strip())
    except InvalidTokenError:
        raise _unauthorized("Invalid or expired token")
