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

import pytest  # noqa: E402

from app.db.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _isolate_app_state():
    from app.core.middleware import rate_limiter
    from app.main import app

    rate_limiter.reset()
    yield
    app.dependency_overrides.clear()
