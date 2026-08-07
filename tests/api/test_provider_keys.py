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

    payload = {"provider": "openai", "key": "sk-test-123"}
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
