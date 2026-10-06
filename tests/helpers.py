"""Shared helpers for tests that need authenticated users."""

import uuid

from fastapi.testclient import TestClient

from app.models.user import User

TEST_PASSWORD = "password123"


def unique_username(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def login(client: TestClient, username: str, password: str = TEST_PASSWORD) -> tuple[dict, int]:
    """Register ``username`` if needed, log in, and return ``(headers, user_id)``."""
    client.post("/auth/register", json={"username": username, "password": password})
    token = client.post("/auth/login", json={"username": username, "password": password}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    return headers, user_id


def make_user(session, username: str | None = None) -> User:
    """Insert a user row directly, for service-level tests that bypass the API."""
    user = User(username=username or unique_username(), password_hash="!")
    session.add(user)
    session.flush()
    return user


def user_id_for(username: str) -> int:
    """Look up the id of a user registered through the API."""
    from app.db.database import SessionLocal

    session = SessionLocal()
    try:
        return session.query(User.id).filter(User.username == username).scalar()
    finally:
        session.close()


def hide_provider(monkeypatch, name: str, reason: str = "Not offered for new keys (test).") -> None:
    """Mark a provider not offered for new keys (ProviderSpec.unavailable) for one test."""
    from dataclasses import replace

    from app.services.llm.registry import PROVIDERS

    monkeypatch.setitem(PROVIDERS, name, replace(PROVIDERS[name], unavailable=reason))
