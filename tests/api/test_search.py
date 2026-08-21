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
