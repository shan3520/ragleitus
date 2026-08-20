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
        assert last_unmatched.timestamp is not None
    finally:
        db.close()
