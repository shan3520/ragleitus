import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.core.middleware import rate_limiter
from app.db.database import get_db
from app.services.document_service import create_document_with_chunks


def _get_authenticated_client(username: str):
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    login_resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


def test_document_stats_endpoint():
    unique_user = f"stats_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        create_document_with_chunks(
            session=db,
            user_id=unique_user,
            title="Doc 1",
            content="Sample text",
            chunk_contents=["Chunk A", "Chunk B"],
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/documents/stats", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_documents"] == 1
    assert data["total_chunks"] == 2
    assert data["avg_chunks_per_document"] == 2.0
