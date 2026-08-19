import uuid
import datetime
from fastapi.testclient import TestClient

from app.main import app
from app.core.middleware import rate_limiter
from app.db.database import get_db
from app.models.document import UnmatchedSearch


def _get_authenticated_client(username: str):
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    login_resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


def test_recent_unanswered_queries():
    unique_user = f"user_recent_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        # Clear out existing for consistent pagination testing
        db.query(UnmatchedSearch).delete()
        
        # Insert a few searches
        db.add(UnmatchedSearch(query_text="recent 1", timestamp=datetime.datetime(2023, 1, 1, 12, 0, 0)))
        db.add(UnmatchedSearch(query_text="recent 2", timestamp=datetime.datetime(2023, 1, 2, 12, 0, 0)))
        db.add(UnmatchedSearch(query_text="recent 3", timestamp=datetime.datetime(2023, 1, 3, 12, 0, 0)))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/unanswered-queries/recent?skip=0&limit=2", headers=headers)
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 2
    # Should be ordered descending by timestamp
    assert results[0]["query_text"] == "recent 3"
    assert results[1]["query_text"] == "recent 2"

    resp2 = client.get("/api/unanswered-queries/recent?skip=2&limit=2", headers=headers)
    assert resp2.status_code == 200
    results2 = resp2.json()
    assert len(results2) == 1
    assert results2[0]["query_text"] == "recent 1"


def test_frequent_unanswered_queries():
    unique_user = f"user_frequent_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        db.query(UnmatchedSearch).delete()

        # Insert multiple identical searches to test grouping
        for _ in range(3):
            db.add(UnmatchedSearch(query_text="apple"))
        for _ in range(5):
            db.add(UnmatchedSearch(query_text="banana"))
        for _ in range(1):
            db.add(UnmatchedSearch(query_text="cherry"))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/unanswered-queries/frequent?limit=10", headers=headers)
    assert resp.status_code == 200
    results = resp.json()
    
    assert len(results) == 3
    # Ordered by count descending
    assert results[0]["query_text"] == "banana"
    assert results[0]["count"] == 5
    
    assert results[1]["query_text"] == "apple"
    assert results[1]["count"] == 3
    
    assert results[2]["query_text"] == "cherry"
    assert results[2]["count"] == 1
