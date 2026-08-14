import tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.middleware import rate_limiter
from app.db.database import get_db
from app.models import Base, ProviderKey


def _setup_test_db(username: str = "key_user"):
    rate_limiter.reset()
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_url = f"sqlite:///{tf.name}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    login_resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    return client, headers, TestingSessionLocal


def test_post_provider_key_stores_encrypted_value():
    client, headers, TestingSessionLocal = _setup_test_db("user_pk1")

    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["provider"] == "openai"

    session = TestingSessionLocal()
    stored = session.query(ProviderKey).filter_by(id=data["id"]).one()
    assert stored.encrypted_key != payload["key"]
    assert stored.provider == payload["provider"]
    session.close()
    app.dependency_overrides.clear()


def test_get_provider_keys_returns_masked_values():
    client, headers, _ = _setup_test_db("user_pk2")

    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload, headers=headers)
    assert resp.status_code == 200
    created_id = resp.json()["id"]

    resp = client.get("/provider-keys", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == created_id
    assert data[0]["provider"] == "openai"
    assert data[0]["masked_key"].endswith("***")
    assert "sk-testkey1234567" not in data[0]["masked_key"]
    app.dependency_overrides.clear()


def test_delete_provider_key_removes_key():
    client, headers, _ = _setup_test_db("user_pk3")

    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload, headers=headers)
    assert resp.status_code == 200
    created_id = resp.json()["id"]

    resp = client.get("/provider-keys", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.delete(f"/provider-keys/{created_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Provider key deleted"

    resp = client.get("/provider-keys", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0
    app.dependency_overrides.clear()


def test_delete_nonexistent_provider_key_returns_404():
    client, headers, _ = _setup_test_db("user_pk4")

    resp = client.delete("/provider-keys/999", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Provider key not found"
    app.dependency_overrides.clear()
