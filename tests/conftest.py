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
# A local HTTP proxy would let outbound requests past the loopback exemption below.
for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_proxy_var, None)

import socket  # noqa: E402

import pytest  # noqa: E402

_real_connect = socket.socket.connect


def _no_network(self, address):
    # Tests must run with no external services (CONTRIBUTING.md). Unix sockets and
    # loopback stay available; anything else fails loudly instead of hanging.
    if self.family == socket.AF_UNIX or (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
        return _real_connect(self, address)
    raise RuntimeError(f"test attempted a network connection to {address!r}")


socket.socket.connect = _no_network

from app.db.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _isolate_app_state():
    from app.core.middleware import login_rate_limiter, rate_limiter
    from app.main import app

    rate_limiter.reset()
    login_rate_limiter.reset()
    yield
    app.dependency_overrides.clear()
