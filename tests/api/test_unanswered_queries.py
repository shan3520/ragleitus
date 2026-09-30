import uuid
import datetime
from datetime import timedelta, timezone
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
        from app.models.query_cluster import QueryCluster
        # Clear out existing for consistent pagination testing
        db.query(QueryCluster).delete()
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
        from app.models.query_cluster import QueryCluster
        db.query(QueryCluster).delete()
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
    payload = resp.json()

    # Response is an envelope object with data and message, not a bare list
    assert isinstance(payload, dict)
    assert set(payload.keys()) == {"data", "message"}
    assert isinstance(payload["message"], str)

    results = payload["data"]

    assert len(results) == 3
    # Ordered by count descending
    assert results[0]["query_text"] == "banana"
    assert results[0]["count"] == 5

    assert results[1]["query_text"] == "apple"
    assert results[1]["count"] == 3

    assert results[2]["query_text"] == "cherry"
    assert results[2]["count"] == 1

    # Individual item schema is unchanged
    for item in results:
        assert set(item.keys()) == {"query_text", "count"}


def test_frequent_unanswered_queries_filters_old_searches():
    unique_user = f"user_frequent_window_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    now = datetime.datetime.now(timezone.utc)
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.query_cluster import QueryCluster
        db.query(QueryCluster).delete()
        db.query(UnmatchedSearch).delete()

        # 'legacy query' lives entirely outside the window
        for _ in range(4):
            db.add(UnmatchedSearch(query_text="legacy query", timestamp=now - timedelta(days=60)))

        # 'fresh query' has one OLD occurrence alongside two recent ones:
        # aggregating before filtering would wrongly count it as 3
        db.add(UnmatchedSearch(query_text="fresh query", timestamp=now - timedelta(days=60)))
        db.add(UnmatchedSearch(query_text="fresh query", timestamp=now - timedelta(hours=1)))
        db.add(UnmatchedSearch(query_text="fresh query", timestamp=now - timedelta(hours=2)))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/unanswered-queries/frequent?days=30&limit=10", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    results = payload["data"]

    # Old occurrences of 'fresh query' must be excluded from its count,
    # and 'legacy query' must not appear at all
    assert len(results) == 1
    assert results[0]["query_text"] == "fresh query"
    assert results[0]["count"] == 2

    # Widening the window brings the old rows back, proving days drives the filter
    resp_wide = client.get("/api/unanswered-queries/frequent?days=90&limit=10", headers=headers)
    assert resp_wide.status_code == 200
    wide = {r["query_text"]: r["count"] for r in resp_wide.json()["data"]}
    assert wide["legacy query"] == 4
    assert wide["fresh query"] == 3


def test_frequent_unanswered_queries_empty_state_message():
    unique_user = f"user_frequent_empty_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    now = datetime.datetime.now(timezone.utc)
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.query_cluster import QueryCluster
        db.query(QueryCluster).delete()
        db.query(UnmatchedSearch).delete()

        # Only stale activity: nothing inside the requested window
        db.add(UnmatchedSearch(query_text="stale query", timestamp=now - timedelta(days=60)))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/unanswered-queries/frequent?days=7&limit=10", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["data"] == []
    # The message must explicitly mention the requested time window
    assert "last 7 days" in payload["message"]


def test_clustered_unanswered_queries():
    unique_user = f"user_clustered_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.query_cluster import QueryCluster
        db.query(QueryCluster).delete()
        db.query(UnmatchedSearch).delete()

        # Insert some similar queries
        db.add(UnmatchedSearch(query_text="how to reset password", timestamp=datetime.datetime(2023, 1, 1, 12, 0, 0)))
        db.add(UnmatchedSearch(query_text="reset password", timestamp=datetime.datetime(2023, 1, 2, 12, 0, 0)))
        db.add(UnmatchedSearch(query_text="forgot password", timestamp=datetime.datetime(2023, 1, 3, 12, 0, 0)))
        db.add(UnmatchedSearch(query_text="apple", timestamp=datetime.datetime(2023, 1, 4, 12, 0, 0)))
        db.add(UnmatchedSearch(query_text="apples", timestamp=datetime.datetime(2023, 1, 5, 12, 0, 0)))
        db.commit()

        from app.models.document import Document
        resolving_doc = Document(title="Password reset guide")
        db.add(resolving_doc)
        db.flush()

        # Mark "apple" cluster as handled
        apple_search = db.query(UnmatchedSearch).filter(UnmatchedSearch.query_text == "apple").first()
        handled_cluster = QueryCluster(id=apple_search.id, status="handled", resolved_by_document_id=resolving_doc.id, resolved_at=datetime.datetime(2023, 1, 6, 12, 0, 0))
        db.add(handled_cluster)
        
        # Add a "regression" cluster
        regression_search = db.query(UnmatchedSearch).filter(UnmatchedSearch.query_text == "apples").first()
        regression_cluster = QueryCluster(id=regression_search.id, status="regression", resolved_by_document_id=resolving_doc.id, resolved_at=datetime.datetime(2023, 1, 6, 12, 0, 0))
        db.add(regression_cluster)
        db.commit()
    finally:
        db.close()

    # Default should omit handled, but include regression
    resp = client.get("/api/unanswered-queries/clustered?threshold=0.3&start=2023-01-01T00:00:00&end=2023-01-06T00:00:00", headers=headers)
    assert resp.status_code == 200
    results = resp.json()
    
    assert len(results) > 0
    # "apple" should not be here
    regression_found = False
    for res in results:
        assert res["canonical_query"] != "apple"
        assert "canonical_query" in res
        assert "volume_count" in res
        assert "timeframe" in res
        assert "id" in res
        assert "resolved_by_document_id" in res
        assert "resolved_at" in res
        assert "queries" not in res
        assert "status" in res
        if res["canonical_query"] == "apples":
            assert res["status"] == "regression"
            regression_found = True
        else:
            assert res["status"] == "open"
    assert regression_found

    # Request with status=handled
    resp_handled = client.get("/api/unanswered-queries/clustered?threshold=0.3&status=handled", headers=headers)
    assert resp_handled.status_code == 200
    handled_results = resp_handled.json()
    
    assert len(handled_results) == 1
    assert handled_results[0]["canonical_query"] == "apple"
    assert handled_results[0]["resolved_by_document_id"] == 1
    assert handled_results[0]["resolved_at"] is not None

def test_clustered_unanswered_queries_auth():
    client = TestClient(app)
    resp = client.get("/api/unanswered-queries/clustered")
    assert resp.status_code == 401

def test_mark_cluster_handled_api():
    unique_user = f"user_cluster_patch_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.query_cluster import QueryCluster
        from app.models.document import Document
        from app.models.document import UnmatchedSearch
        
        db.query(QueryCluster).delete()
        db.query(UnmatchedSearch).delete()
        
        doc = Document(user_id=unique_user, title="Test Doc", content="Content", status="completed")
        db.add(doc)
        db.commit()

        # create a search so the cluster has an id
        search1 = UnmatchedSearch(query_text="cluster test query", timestamp=datetime.datetime(2023, 5, 1, 10, 0, 0))
        db.add(search1)
        db.commit()
        
        # create a similar search with a later timestamp
        search2 = UnmatchedSearch(query_text="cluster test query", timestamp=datetime.datetime(2023, 5, 2, 10, 0, 0))
        db.add(search2)
        db.commit()

        cluster = QueryCluster(id=search1.id, status="open")
        db.add(cluster)
        db.commit()
        
        cluster_id = cluster.id
        doc_id = doc.id
        
        resp = client.patch(f"/api/unanswered-queries/clusters/{cluster_id}", json={"document_id": doc_id}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Cluster marked as handled"
        assert data["status"] == "handled"
        assert data["document_id"] == doc_id
        
        db.refresh(cluster)
        assert cluster.last_resolved_query_timestamp == datetime.datetime(2023, 5, 2, 10, 0, 0)
        
        resp_404 = client.patch(f"/api/unanswered-queries/clusters/{cluster_id}", json={"document_id": 99999}, headers=headers)
        assert resp_404.status_code == 404
        
        other_doc = Document(user_id="other_user", title="Other", content="Other", status="completed")
        db.add(other_doc)
        db.commit()
        other_doc_id = other_doc.id
        
        resp_404_other = client.patch(f"/api/unanswered-queries/clusters/{cluster_id}", json={"document_id": other_doc_id}, headers=headers)
        assert resp_404_other.status_code == 404
        
    finally:
        db.close()
