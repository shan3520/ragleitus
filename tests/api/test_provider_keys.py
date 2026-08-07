import os
import tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.main import app
from app.models import Base, ProviderKey


def test_post_provider_key_stores_encrypted_value():
    # Use a temporary sqlite file for isolation
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_path = tf.name
    db_url = f"sqlite:///{db_path}"

    os.environ["DATABASE_URL"] = db_url
    os.environ["PROVIDER_KEY_SECRET"] = "test-secret"

    # create tables
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    client = TestClient(app)

    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["provider"] == "openai"

    # verify stored value is not the plaintext
    Session = sessionmaker(bind=engine)
    session = Session()
    stored = session.query(ProviderKey).filter_by(id=data["id"]).one()
    assert stored.encrypted_key != payload["key"]
    assert stored.provider == payload["provider"]

    session.close()


def test_get_provider_keys_returns_masked_values():
    # Use a temporary sqlite file for isolation
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_path = tf.name
    db_url = f"sqlite:///{db_path}"

    os.environ["DATABASE_URL"] = db_url
    os.environ["PROVIDER_KEY_SECRET"] = "test-secret"

    # create tables
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    client = TestClient(app)

    # Create a provider key
    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload)
    assert resp.status_code == 200
    created_id = resp.json()["id"]

    # Get the provider keys
    resp = client.get("/provider-keys")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == created_id
    assert data[0]["provider"] == "openai"
    # Verify the key is masked and doesn't contain the original key
    assert data[0]["masked_key"].endswith("***")
    assert "sk-testkey1234567" not in data[0]["masked_key"]
    assert len(data[0]["masked_key"]) == 6  # 3 chars + "***"


def test_delete_provider_key_removes_key():
    # Use a temporary sqlite file for isolation
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_path = tf.name
    db_url = f"sqlite:///{db_path}"

    os.environ["DATABASE_URL"] = db_url
    os.environ["PROVIDER_KEY_SECRET"] = "test-secret"

    # create tables
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    client = TestClient(app)

    # Create a provider key
    payload = {"provider": "openai", "key": "sk-testkey1234567"}
    resp = client.post("/provider-keys", json=payload)
    assert resp.status_code == 200
    created_id = resp.json()["id"]

    # Verify the key exists
    resp = client.get("/provider-keys")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Delete the key
    resp = client.delete(f"/provider-keys/{created_id}")
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Provider key deleted"

    # Verify the key is gone
    resp = client.get("/provider-keys")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_delete_nonexistent_provider_key_returns_404():
    # Use a temporary sqlite file for isolation
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_path = tf.name
    db_url = f"sqlite:///{db_path}"

    os.environ["DATABASE_URL"] = db_url
    os.environ["PROVIDER_KEY_SECRET"] = "test-secret"

    # create tables
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    client = TestClient(app)

    # Try to delete a non-existent key
    resp = client.delete("/provider-keys/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Provider key not found"
