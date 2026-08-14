import tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import get_db
from app.models import Base, ProviderKey


def _setup_test_db():
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
    return engine, TestingSessionLocal


def test_post_provider_key_stores_encrypted_value():
    engine, TestingSessionLocal = _setup_test_db()
    client = TestClient(app)

    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload)
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
    _setup_test_db()
    client = TestClient(app)

    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload)
    assert resp.status_code == 200
    created_id = resp.json()["id"]

    resp = client.get("/provider-keys")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == created_id
    assert data[0]["provider"] == "openai"
    assert data[0]["masked_key"].endswith("***")
    assert "sk-testkey1234567" not in data[0]["masked_key"]
    app.dependency_overrides.clear()


def test_delete_provider_key_removes_key():
    _setup_test_db()
    client = TestClient(app)

    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload)
    assert resp.status_code == 200
    created_id = resp.json()["id"]

    resp = client.get("/provider-keys")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.delete(f"/provider-keys/{created_id}")
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Provider key deleted"

    resp = client.get("/provider-keys")
    assert resp.status_code == 200
    assert len(resp.json()) == 0
    app.dependency_overrides.clear()


def test_delete_nonexistent_provider_key_returns_404():
    _setup_test_db()
    client = TestClient(app)

    resp = client.delete("/provider-keys/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Provider key not found"
    app.dependency_overrides.clear()
