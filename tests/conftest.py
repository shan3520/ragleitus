"""Test-wide configuration.

Environment variables are set before anything under `app` is imported, so
the application runs against a throwaway SQLite file, an in-process Qdrant
store and a deterministic fake embedder. No external services are needed.
"""

import os
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="ragforge-tests-")

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"
os.environ["JWT_SECRET"] = "test-jwt-secret-not-for-production"
os.environ["PROVIDER_KEY_SECRET"] = "test-provider-key-secret-not-for-production"
os.environ["VECTOR_STORE_URL"] = ":memory:"
os.environ["EMBEDDING_BACKEND"] = "fake"
os.environ["RERANK_BACKEND"] = "fake"

import pytest  # noqa: E402

from tests import network  # noqa: E402

# No outbound connections, except to loopback (see tests/network.py).
network.block()

from app.db.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _no_retry_waits(monkeypatch):
    """Provider calls retried after a 429/503 (experiments) retry at once in tests."""
    from app.services.llm import retry

    monkeypatch.setattr(retry, "MAX_WAIT_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def _isolate_app_state():
    from app.core.middleware import login_rate_limiter, rate_limiter
    from app.main import app

    rate_limiter.reset()
    login_rate_limiter.reset()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def vector_stores(monkeypatch):
    """A fresh in-memory Qdrant behind every collection (vector_store.store_for),
    so vectors from one test can't turn up in another."""
    from qdrant_client import QdrantClient

    from app.services import vector_store

    client = QdrantClient(location=":memory:")
    monkeypatch.setattr(vector_store, "_client", lambda: client)
    vector_store.store_for.cache_clear()
    yield client
    vector_store.store_for.cache_clear()
