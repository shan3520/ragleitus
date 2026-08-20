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
    assert "search_analytics" in data
    assert "top_queries" in data["search_analytics"]
    assert "top_documents" in data["search_analytics"]

def test_popular_searches_endpoint():
    unique_user = f"stats_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        logs = [SearchQueryLog(query_text="popular_query", timestamp=now) for _ in range(5)]
        db.add_all(logs)
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/stats/popular-searches?limit=1000", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(d["query"] == "popular_query" and d["count"] >= 5 for d in data)

def test_popular_documents_endpoint():
    unique_user = f"stats_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    doc_id = None
    try:
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        doc = Document(title="PopDoc", status="ready")
        db.add(doc)
        db.commit()
        doc_id = doc.id
        
        log = SearchQueryLog(query_text="pop_doc_query", timestamp=now)
        db.add(log)
        db.commit()
        
        rs = [DocumentRetrievalLog(query_log_id=log.id, document_id=doc_id) for _ in range(100)]
        db.add_all(rs)
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/stats/popular-documents?limit=1000", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(d["document_id"] == doc_id and d["count"] >= 100 for d in data)
