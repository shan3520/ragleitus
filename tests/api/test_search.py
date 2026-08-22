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


def test_search_documents_endpoint():
    from app.models.document import SearchQueryLog, DocumentRetrievalLog

    unique_user = f"user_search_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        doc = create_document_with_chunks(
            session=db,
            user_id=unique_user,
            title="Architecture Guidelines",
            content="This document covers FastAPI app structure and python coding conventions.",
            chunk_contents=["FastAPI app structure", "python coding conventions"],
        )
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    resp = client.get("/api/documents/search?q=FastAPI", headers=headers)
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["title"] == "Architecture Guidelines"
    assert results[0]["score"] > 0

    # Verify background logging
    db_gen = get_db()
    db = next(db_gen)
    try:
        last_log = db.query(SearchQueryLog).order_by(SearchQueryLog.id.desc()).first()
        assert last_log is not None
        assert last_log.query_text == "FastAPI"
        assert last_log.duration_ms is not None
        assert last_log.duration_ms >= 0
        
        retrievals = db.query(DocumentRetrievalLog).filter(DocumentRetrievalLog.query_log_id == last_log.id).all()
        assert len(retrievals) == 1
        assert retrievals[0].document_id == doc_id
    finally:
        db.close()

def test_search_documents_endpoint_empty():
    from app.models.document import UnmatchedSearch

    unique_user = f"user_search_empty_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        initial_count = db.query(UnmatchedSearch).count()
    finally:
        db.close()

    resp = client.get("/api/documents/search?q=NonExistentTerm", headers=headers)
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 0

    db_gen = get_db()
    db = next(db_gen)
    try:
        final_count = db.query(UnmatchedSearch).count()
        assert final_count == initial_count + 1

        last_unmatched = db.query(UnmatchedSearch).order_by(UnmatchedSearch.id.desc()).first()
        assert last_unmatched.query_text == "NonExistentTerm"
        assert last_unmatched.duration_ms is not None
        assert last_unmatched.timestamp is not None
    finally:
        db.close()


def _seed_retrieval_log(username: str):
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    login_resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import DocumentRetrievalLog, SearchQueryLog

        doc = create_document_with_chunks(
            session=db,
            user_id=username,
            title="Open Tracking Doc",
            content="Content for open tracking.",
            chunk_contents=["open tracking chunk"],
        )
        query_log = SearchQueryLog(query_text="open tracking probe")
        db.add(query_log)
        db.commit()
        retrieval_log = DocumentRetrievalLog(query_log_id=query_log.id, document_id=doc.id)
        db.add(retrieval_log)
        db.commit()
        return client, headers, query_log.id, doc.id
    finally:
        db.close()


def test_log_document_open_records_timestamp():
    from app.models.document import DocumentRetrievalLog

    unique_user = f"user_open_{uuid.uuid4().hex[:8]}"
    client, headers, search_id, document_id = _seed_retrieval_log(unique_user)

    resp = client.post(
        f"/api/documents/search/{search_id}/documents/{document_id}/open",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # Re-read through a fresh session so a 200 without persistence fails.
    db_gen = get_db()
    db = next(db_gen)
    try:
        row = (
            db.query(DocumentRetrievalLog)
            .filter(
                DocumentRetrievalLog.query_log_id == search_id,
                DocumentRetrievalLog.document_id == document_id,
            )
            .first()
        )
        assert row is not None
        assert row.opened_at is not None
    finally:
        db.close()


def test_log_document_open_missing_log_returns_404_without_creating():
    from app.models.document import DocumentRetrievalLog

    unique_user = f"user_open_missing_{uuid.uuid4().hex[:8]}"
    client, headers, _, _ = _seed_retrieval_log(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        count_before = db.query(DocumentRetrievalLog).count()
    finally:
        db.close()

    resp = client.post(
        "/api/documents/search/999999999/documents/999999999/open",
        headers=headers,
    )
    assert resp.status_code == 404

    db_gen = get_db()
    db = next(db_gen)
    try:
        count_after = db.query(DocumentRetrievalLog).count()
        assert count_after == count_before
        assert (
            db.query(DocumentRetrievalLog)
            .filter(
                DocumentRetrievalLog.query_log_id == 999999999,
                DocumentRetrievalLog.document_id == 999999999,
            )
            .first()
            is None
        )
    finally:
        db.close()


def test_list_saved_searches_empty():
    from app.models.document import SavedSearch

    unique_user = f"user_saved_empty_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    resp = client.get("/api/documents/saved-searches", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    # Nothing was persisted for this user by the empty listing.
    db_gen = get_db()
    db = next(db_gen)
    try:
        assert (
            db.query(SavedSearch).filter(SavedSearch.user_id == unique_user).count() == 0
        )
    finally:
        db.close()


def test_upsert_saved_search_creates_new():
    from app.models.document import SavedSearch

    unique_user = f"user_saved_new_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    payload = {
        "search_name": "daily-report",
        "query_text": "quarterly revenue",
        "applied_filters": {"status": "completed", "group": "finance"},
    }
    resp = client.put("/api/documents/saved-searches", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] > 0
    assert body["user_id"] == unique_user
    assert body["search_name"] == "daily-report"
    assert body["query_text"] == "quarterly revenue"
    assert body["applied_filters"] == {"status": "completed", "group": "finance"}

    # The returned id must belong to a row actually persisted for this user.
    db_gen = get_db()
    db = next(db_gen)
    try:
        rows = db.query(SavedSearch).filter(SavedSearch.user_id == unique_user).all()
        assert len(rows) == 1
        assert rows[0].id == body["id"]
        assert rows[0].search_name == "daily-report"
        assert rows[0].query_text == "quarterly revenue"
        assert rows[0].applied_filters == {"status": "completed", "group": "finance"}
    finally:
        db.close()


def test_upsert_saved_search_updates_existing():
    from app.models.document import SavedSearch

    unique_user = f"user_saved_update_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    first = client.put(
        "/api/documents/saved-searches",
        json={"search_name": "triage", "query_text": "error logs", "applied_filters": None},
        headers=headers,
    )
    assert first.status_code == 200
    original_id = first.json()["id"]

    second = client.put(
        "/api/documents/saved-searches",
        json={"search_name": "triage", "query_text": "warning logs", "applied_filters": {"level": "warn"}},
        headers=headers,
    )
    assert second.status_code == 200
    updated = second.json()
    assert updated["id"] == original_id
    assert updated["user_id"] == unique_user
    assert updated["search_name"] == "triage"
    assert updated["query_text"] == "warning logs"
    assert updated["applied_filters"] == {"level": "warn"}

    # Exactly one row must exist for (user, search_name): an upsert must not
    # insert a duplicate under the same name, nor leave stale values behind.
    db_gen = get_db()
    db = next(db_gen)
    try:
        rows = (
            db.query(SavedSearch)
            .filter(SavedSearch.user_id == unique_user, SavedSearch.search_name == "triage")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == original_id
        assert rows[0].query_text == "warning logs"
        assert rows[0].applied_filters == {"level": "warn"}
    finally:
        db.close()


def test_list_saved_searches_returns_user_searches():
    from app.models.document import SavedSearch

    user_a = f"user_saved_list_a_{uuid.uuid4().hex[:8]}"
    user_b = f"user_saved_list_b_{uuid.uuid4().hex[:8]}"
    client_a, headers_a = _get_authenticated_client(user_a)

    resp_a_put = client_a.put(
        "/api/documents/saved-searches",
        json={"search_name": "alpha", "query_text": "alpha terms", "applied_filters": {"tag": "a"}},
        headers=headers_a,
    )
    assert resp_a_put.status_code == 200
    alpha_id = resp_a_put.json()["id"]
    resp_a_put2 = client_a.put(
        "/api/documents/saved-searches",
        json={"search_name": "beta", "query_text": "beta terms"},
        headers=headers_a,
    )
    assert resp_a_put2.status_code == 200
    beta_id = resp_a_put2.json()["id"]

    client_b, headers_b = _get_authenticated_client(user_b)
    # Same name as one of user A's saved searches: names are only unique per user.
    resp_b_put = client_b.put(
        "/api/documents/saved-searches",
        json={"search_name": "alpha", "query_text": "b sees different docs"},
        headers=headers_b,
    )
    assert resp_b_put.status_code == 200
    b_alpha_id = resp_b_put.json()["id"]
    assert b_alpha_id != alpha_id

    resp_a_get = client_a.get("/api/documents/saved-searches", headers=headers_a)
    assert resp_a_get.status_code == 200
    listings_a = resp_a_get.json()
    assert len(listings_a) == 2
    assert {item["id"] for item in listings_a} == {alpha_id, beta_id}
    assert {item["search_name"] for item in listings_a} == {"alpha", "beta"}
    for item in listings_a:
        assert item["user_id"] == user_a

    resp_b_get = client_b.get("/api/documents/saved-searches", headers=headers_b)
    assert resp_b_get.status_code == 200
    listings_b = resp_b_get.json()
    assert len(listings_b) == 1
    assert listings_b[0]["id"] == b_alpha_id
    assert listings_b[0]["user_id"] == user_b
    assert listings_b[0]["search_name"] == "alpha"

    # Cross-user isolation at the persistence layer: user B must own exactly
    # one row, and none of user A's rows may carry B's identity.
    db_gen = get_db()
    db = next(db_gen)
    try:
        assert db.query(SavedSearch).filter(SavedSearch.user_id == user_a).count() == 2
        assert db.query(SavedSearch).filter(SavedSearch.user_id == user_b).count() == 1
        assert (
            db.query(SavedSearch)
            .filter(SavedSearch.user_id == user_b, SavedSearch.id.in_([alpha_id, beta_id]))
            .count()
            == 0
        )
    finally:
        db.close()
