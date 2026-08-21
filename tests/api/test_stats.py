import json
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.errors import NoSearchActivityError
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
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import Document, Chunk
        db.query(Chunk).delete()
        db.query(Document).delete()
        db.commit()
    finally:
        db.close()

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

    try:
        resp = client.get("/api/documents/stats", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] == 1
        assert data["total_chunks"] == 2
        assert data["avg_chunks_per_document"] == 2.0
        assert "search_analytics" in data
        assert "top_queries" in data["search_analytics"]
        assert "top_documents" in data["search_analytics"]
    finally:
        db_gen = get_db()
        cleanup_db = next(db_gen)
        try:
            from app.models.document import Document, Chunk
            cleanup_db.query(Chunk).delete()
            cleanup_db.query(Document).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()

def test_popular_searches_endpoint():
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog
        db.query(SearchQueryLog).delete()
        db.commit()
    finally:
        db.close()

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

    try:
        resp = client.get("/api/stats/popular-searches?limit=1000", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(d["query"] == "popular_query" and d["count"] >= 5 for d in data)
    finally:
        db_gen = get_db()
        cleanup_db = next(db_gen)
        try:
            from app.models.document import SearchQueryLog
            cleanup_db.query(SearchQueryLog).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()

def test_popular_documents_endpoint():
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
        db.query(DocumentRetrievalLog).delete()
        db.query(SearchQueryLog).delete()
        db.query(Chunk).delete()
        db.query(Document).delete()
        db.commit()
    finally:
        db.close()

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

    try:
        resp = client.get("/api/stats/popular-documents?limit=1000", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(d["document_id"] == doc_id and d["count"] >= 100 for d in data)
    finally:
        db_gen = get_db()
        cleanup_db = next(db_gen)
        try:
            from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
            cleanup_db.query(DocumentRetrievalLog).delete()
            cleanup_db.query(SearchQueryLog).delete()
            cleanup_db.query(Chunk).delete()
            cleanup_db.query(Document).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()

def test_popular_searches_honors_days_and_raises_on_empty_window():
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog
        db.query(SearchQueryLog).delete()
        db.commit()
    finally:
        db.close()

    unique_user = f"stats_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    # With zero search logs, the request must surface NoSearchActivityError
    # rather than quietly returning 200 OK with an empty list.
    with pytest.raises(NoSearchActivityError):
        client.get("/api/stats/popular-searches?days=30", headers=headers)

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        logs = (
            [SearchQueryLog(query_text="fresh_query", timestamp=now) for _ in range(2)]
            + [SearchQueryLog(query_text="stale_query", timestamp=now - timedelta(days=20))]
        )
        db.add_all(logs)
        db.commit()
    finally:
        db.close()

    try:
        # days=7 must exclude the 20-day-old query. If the backend ignored
        # the ?days parameter (defaulting to 30 or not filtering at all),
        # stale_query would appear here and fail the assertion.
        resp = client.get("/api/stats/popular-searches?days=7&limit=1000", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert [d["query"] for d in data] == ["fresh_query"]
        assert data[0]["count"] == 2
    finally:
        db_gen = get_db()
        cleanup_db = next(db_gen)
        try:
            from app.models.document import SearchQueryLog
            cleanup_db.query(SearchQueryLog).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()

def test_popular_documents_honors_days_and_raises_on_empty_window():
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
        db.query(DocumentRetrievalLog).delete()
        db.query(SearchQueryLog).delete()
        db.query(Chunk).delete()
        db.query(Document).delete()
        db.commit()
    finally:
        db.close()

    unique_user = f"stats_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    # Zero activity in the requested window: error state, not an empty 200.
    with pytest.raises(NoSearchActivityError):
        client.get("/api/stats/popular-documents?days=30", headers=headers)

    db_gen = get_db()
    db = next(db_gen)
    fresh_doc_id, stale_doc_id = None, None
    try:
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        doc_fresh = Document(title="FreshDoc", status="ready")
        doc_stale = Document(title="StaleDoc", status="ready")
        db.add_all([doc_fresh, doc_stale])
        db.commit()
        fresh_doc_id, stale_doc_id = doc_fresh.id, doc_stale.id

        fresh_log = SearchQueryLog(query_text="fresh_doc_query", timestamp=now)
        stale_log = SearchQueryLog(query_text="stale_doc_query", timestamp=now - timedelta(days=20))
        db.add_all([fresh_log, stale_log])
        db.commit()

        rs = [
            DocumentRetrievalLog(query_log_id=fresh_log.id, document_id=fresh_doc_id)
            for _ in range(3)
        ] + [
            DocumentRetrievalLog(query_log_id=stale_log.id, document_id=stale_doc_id)
            for _ in range(2)
        ]
        db.add_all(rs)
        db.commit()
    finally:
        db.close()

    try:
        # days=7 must exclude retrievals driven by the 20-day-old query. If
        # ?days were ignored (30-day default or no filter), StaleDoc would
        # appear here and fail the assertion.
        resp = client.get("/api/stats/popular-documents?days=7&limit=1000", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert [d["document_id"] for d in data] == [fresh_doc_id]
        assert data[0]["count"] == 3
        assert stale_doc_id not in {d["document_id"] for d in data}
    finally:
        db_gen = get_db()
        cleanup_db = next(db_gen)
        try:
            from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
            cleanup_db.query(DocumentRetrievalLog).delete()
            cleanup_db.query(SearchQueryLog).delete()
            cleanup_db.query(Chunk).delete()
            cleanup_db.query(Document).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_underperforming_documents_endpoint():
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.feedback import SearchFeedback, document_feedback
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
        db.execute(document_feedback.delete())
        db.query(SearchFeedback).delete()
        db.query(DocumentRetrievalLog).delete()
        db.query(SearchQueryLog).delete()
        db.query(Chunk).delete()
        db.query(Document).delete()
        db.commit()
    finally:
        db.close()

    unique_user = f"stats_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    
    doc1_id, doc2_id, doc3_id = None, None, None
    try:
        from app.models.feedback import SearchFeedback
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        doc1 = Document(title="Doc 1", status="ready", user_id=unique_user)
        doc2 = Document(title="Doc 2", status="ready", user_id=unique_user)
        doc3 = Document(title="Doc 3", status="ready", user_id=unique_user)
        db.add_all([doc1, doc2, doc3])
        db.commit()
        doc1_id, doc2_id, doc3_id = doc1.id, doc2.id, doc3.id
        
        log = SearchQueryLog(query_text="bad_doc_query", timestamp=now)
        db.add(log)
        db.commit()
        
        # Doc 1: 10 retrievals, 8 negative feedbacks (0.8)
        # Doc 2: 6 retrievals, 2 negative feedbacks (0.33)
        # Doc 3: 4 retrievals, 4 negative feedbacks (1.0) -> Should be filtered out by min_retrievals=5
        
        rs = [DocumentRetrievalLog(query_log_id=log.id, document_id=doc1_id) for _ in range(10)]
        rs += [DocumentRetrievalLog(query_log_id=log.id, document_id=doc2_id) for _ in range(6)]
        rs += [DocumentRetrievalLog(query_log_id=log.id, document_id=doc3_id) for _ in range(4)]
        db.add_all(rs)
        db.commit()
        
        f1 = [SearchFeedback(search_log_id=log.id, is_positive=False, created_at=now) for _ in range(8)]
        f2 = [SearchFeedback(search_log_id=log.id, is_positive=False, created_at=now) for _ in range(2)]
        f3 = [SearchFeedback(search_log_id=log.id, is_positive=False, created_at=now) for _ in range(4)]
        
        for f in f1:
            f.documents.append(doc1)
        for f in f2:
            f.documents.append(doc2)
        for f in f3:
            f.documents.append(doc3)
            
        db.add_all(f1 + f2 + f3)
        db.commit()
    finally:
        db.close()

    try:
        resp = client.get("/api/stats/underperforming-documents?min_retrievals=5", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Should be sorted by disappointment_ratio descending
        assert data[0]["document_id"] == doc1_id
        assert data[0]["disappointment_ratio"] == 0.8
        assert data[1]["document_id"] == doc2_id
        assert round(data[1]["disappointment_ratio"], 2) == 0.33
        
        # Test with min_retrievals=4 to include doc3 (ratio 1.0)
        resp2 = client.get("/api/stats/underperforming-documents?min_retrievals=4", headers=headers)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2) == 3
        assert data2[0]["document_id"] == doc3_id
        assert data2[0]["disappointment_ratio"] == 1.0
        assert data2[1]["document_id"] == doc1_id
    finally:
        db_gen = get_db()
        cleanup_db = next(db_gen)
        try:
            from app.models.feedback import SearchFeedback, document_feedback
            from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
            cleanup_db.execute(document_feedback.delete())
            cleanup_db.query(SearchFeedback).delete()
            cleanup_db.query(DocumentRetrievalLog).delete()
            cleanup_db.query(SearchQueryLog).delete()
            cleanup_db.query(Chunk).delete()
            cleanup_db.query(Document).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()

def test_underperforming_documents_excludes_zero_returns_and_honors_min_shown():
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.feedback import SearchFeedback, document_feedback
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
        db.execute(document_feedback.delete())
        db.query(SearchFeedback).delete()
        db.query(DocumentRetrievalLog).delete()
        db.query(SearchQueryLog).delete()
        db.query(Chunk).delete()
        db.query(Document).delete()
        db.commit()
    finally:
        db.close()

    unique_user = f"stats_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)

    doc_zero_id, doc_mid_id, doc_high_id = None, None, None
    try:
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        doc_zero = Document(title="Zero returns", status="ready", user_id=unique_user)
        doc_mid = Document(title="Mid traffic", status="ready", user_id=unique_user)
        doc_high = Document(title="High traffic", status="ready", user_id=unique_user)
        db.add_all([doc_zero, doc_mid, doc_high])
        db.commit()
        doc_zero_id, doc_mid_id, doc_high_id = doc_zero.id, doc_mid.id, doc_high.id

        log = SearchQueryLog(query_text="min_shown probe", timestamp=now)
        db.add(log)
        db.commit()

        # doc_mid: 6 retrievals (clears default min_retrievals=5 but not 8)
        # doc_high: 9 retrievals; doc_zero: never retrieved at all.
        rs = [DocumentRetrievalLog(query_log_id=log.id, document_id=doc_mid_id) for _ in range(6)]
        rs += [DocumentRetrievalLog(query_log_id=log.id, document_id=doc_high_id) for _ in range(9)]
        db.add_all(rs)
        db.commit()
    finally:
        db.close()

    try:
        # min_shown=8: only the 9-retrieval document clears the bar. The
        # 6-retrieval document passes the default min_retrievals floor, so if
        # the endpoint ignored min_shown it would wrongly appear here.
        resp = client.get("/api/stats/underperforming-documents?min_shown=8", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert [item["document_id"] for item in data] == [doc_high_id]

        # Without min_shown the 6-retrieval document qualifies again.
        resp_default = client.get("/api/stats/underperforming-documents", headers=headers)
        assert resp_default.status_code == 200
        default_ids = {item["document_id"] for item in resp_default.json()}
        assert default_ids == {doc_mid_id, doc_high_id}

        # The zero-return document is never returned under any threshold.
        assert doc_zero_id not in default_ids
    finally:
        db_gen = get_db()
        cleanup_db = next(db_gen)
        try:
            from app.models.feedback import SearchFeedback, document_feedback
            from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document, Chunk
            cleanup_db.execute(document_feedback.delete())
            cleanup_db.query(SearchFeedback).delete()
            cleanup_db.query(DocumentRetrievalLog).delete()
            cleanup_db.query(SearchQueryLog).delete()
            cleanup_db.query(Chunk).delete()
            cleanup_db.query(Document).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def _wipe_documents_and_logs():
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import Document, Chunk, SearchQueryLog, DocumentRetrievalLog
        db.query(DocumentRetrievalLog).delete()
        db.query(SearchQueryLog).delete()
        db.query(Chunk).delete()
        db.query(Document).delete()
        db.commit()
    finally:
        db.close()


def test_dead_documents_no_activity_returns_plain_text_not_json():
    rate_limiter.reset()
    _wipe_documents_and_logs()

    client = TestClient(app)
    resp = client.get("/stats/dead-documents?days=30")

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("text/plain")
    assert "No search activity" in resp.text
    # A default FastAPI HTTPException payload would parse as JSON; the plain
    # text warning must not.
    with pytest.raises(json.JSONDecodeError):
        json.loads(resp.text)

    # The un-prefixed alias on the stats router serves the same payload.
    resp_alias = client.get("/dead-documents?days=30")
    assert resp_alias.status_code == 400
    assert resp_alias.headers["content-type"].startswith("text/plain")


def test_dead_documents_sorted_newest_first():
    rate_limiter.reset()
    _wipe_documents_and_logs()

    unique_user = f"dead_docs_user_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()

    db_gen = get_db()
    db = next(db_gen)
    ids_by_title = {}
    try:
        from app.models.document import Document, SearchQueryLog
        # Search activity inside the window so dead documents can be determined.
        db.add(SearchQueryLog(query_text="dead docs probe", timestamp=now))
        db.commit()

        # Insert oldest-created document first so table insertion order is the
        # opposite of the required response order: an unsorted pass-through of
        # insertion/rowid order would come back oldest-first and fail below.
        for title, age_days in (("oldest", 60), ("middle", 50), ("newest", 40)):
            doc = Document(
                user_id=unique_user,
                title=title,
                status="ready",
                created_at=now - timedelta(days=age_days),
            )
            db.add(doc)
            db.commit()
            ids_by_title[title] = doc.id
    finally:
        db.close()

    try:
        client = TestClient(app)
        resp = client.get("/stats/dead-documents?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        titles = [item["title"] for item in data]
        assert titles == ["newest", "middle", "oldest"]
        assert [item["id"] for item in data] == [
            ids_by_title["newest"],
            ids_by_title["middle"],
            ids_by_title["oldest"],
        ]
    finally:
        _wipe_documents_and_logs()


def test_dead_documents_response_contains_only_id_title_created_at():
    rate_limiter.reset()
    _wipe_documents_and_logs()

    unique_user = f"dead_docs_user_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()

    db_gen = get_db()
    db = next(db_gen)
    dead_id = None
    try:
        from app.models.document import Document, SearchQueryLog
        db.add(SearchQueryLog(query_text="dead docs fields probe", timestamp=now))
        db.commit()
        doc = Document(
            user_id=unique_user,
            title="field probe",
            status="ready",
            content="internal payload that must not leak",
            created_at=now - timedelta(days=45),
        )
        db.add(doc)
        db.commit()
        dead_id = doc.id
    finally:
        db.close()

    try:
        client = TestClient(app)
        resp = client.get("/stats/dead-documents?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        # Exactly the three public fields - no leaked DB columns such as
        # status, content, user_id or sha256.
        assert set(item.keys()) == {"id", "title", "created_at"}
        assert item["id"] == dead_id
        assert item["title"] == "field probe"
        datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
    finally:
        _wipe_documents_and_logs()
