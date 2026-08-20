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
