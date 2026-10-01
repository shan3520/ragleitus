import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.core.middleware import rate_limiter
from tests.helpers import user_id_for
from app.db.database import get_db

def _get_authenticated_client(username: str):
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    login_resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers

def test_recent_negative_feedback_endpoint():
    unique_user = f"feedback_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)
    uid = user_id_for(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog
        from app.models.feedback import SearchFeedback
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # Create a search log
        log = SearchQueryLog(user_id=uid, 
            query_text="negative feedback query", 
            generated_answer="this is a bad answer", 
            timestamp=now
        )
        db.add(log)
        db.commit()
        
        # Create negative feedback for it
        feedback = SearchFeedback(
            search_log_id=log.id,
            is_positive=False,
            comment="terrible answer",
            created_at=now
        )
        db.add(feedback)
        db.commit()
        
    finally:
        db.close()

    resp = client.get("/api/feedback/negative?limit=10", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    
    # Check if the negative feedback is in the response
    found = False
    for d in data:
        if d["query_text"] == "negative feedback query":
            assert d["generated_answer"] == "this is a bad answer"
            assert d["comment"] == "terrible answer"
            found = True
            break
            
    assert found

def test_top_negative_feedback_queries_endpoint():
    unique_user = f"top_feedback_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)
    uid = user_id_for(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog
        from app.models.feedback import SearchFeedback
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        unique_suffix = uuid.uuid4().hex[:8]
        query1_text = f"how to do X {unique_suffix}"
        query2_text = f"how to do Y {unique_suffix}"
        
        # Create search logs for query 1
        log1a = SearchQueryLog(user_id=uid, query_text=query1_text, generated_answer="A1", timestamp=now)
        log1b = SearchQueryLog(user_id=uid, query_text=query1_text, generated_answer="A2", timestamp=now)
        # Create search logs for query 2
        log2a = SearchQueryLog(user_id=uid, query_text=query2_text, generated_answer="B1", timestamp=now)
        
        db.add_all([log1a, log1b, log2a])
        db.commit()
        
        # Create negative feedback: 2 for query 1, 1 for query 2
        fb1a = SearchFeedback(search_log_id=log1a.id, is_positive=False, comment="bad1", created_at=now)
        fb1b = SearchFeedback(search_log_id=log1b.id, is_positive=False, comment="bad2", created_at=now)
        fb2a = SearchFeedback(search_log_id=log2a.id, is_positive=False, comment="bad3", created_at=now)
        
        # Add a positive feedback for query 2 to ensure it's filtered
        fb2pos = SearchFeedback(search_log_id=log2a.id, is_positive=True, comment="good", created_at=now)
        
        db.add_all([fb1a, fb1b, fb2a, fb2pos])
        db.commit()
        
    finally:
        db.close()

    resp = client.get("/api/feedback/top-negative-queries?limit=100", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    
    # We should have at least 2 items.
    assert len(data) >= 2
    
    # Since other tests might have added data, we will just filter to ours to verify logic
    # Find our queries
    q1_data = next((d for d in data if d["query_text"] == query1_text), None)
    q2_data = next((d for d in data if d["query_text"] == query2_text), None)
    
    assert q1_data is not None
    assert q2_data is not None
    
    assert q1_data["count"] >= 2
    assert q2_data["count"] >= 1
    
    # Also verify they are ordered by count descending
    # Find their indices in the result list
    idx1 = data.index(q1_data)
    idx2 = data.index(q2_data)
    
    # query1 has more negative feedbacks than query2, so it should appear before it
    # Assuming no other tests insert so much that q2 has > q1.
    # Wait, if q1 has 2, and q2 has 1. If no other test adds query1_text/query2_text, q1 should be > q2.
    # Let's use very unique queries.
    assert q1_data["count"] > q2_data["count"]
    assert idx1 < idx2

def test_submit_negative_feedback_links_documents():
    unique_user = f"submit_feedback_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)
    uid = user_id_for(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document
        from app.models.feedback import SearchFeedback
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # Create a document
        doc = Document(user_id=uid, title="test doc", content="test content", status="processed")
        db.add(doc)
        db.commit()
        
        # Create a search log
        log = SearchQueryLog(user_id=uid, 
            query_text="query with retrieval", 
            generated_answer="answer", 
            timestamp=now
        )
        db.add(log)
        db.commit()
        
        # Create a retrieval log
        retrieval = DocumentRetrievalLog(
            query_log_id=log.id,
            document_id=doc.id
        )
        db.add(retrieval)
        db.commit()
        
        log_id = log.id
        doc_id = doc.id
    finally:
        db.close()
        
    # Submit feedback via API
    resp = client.post(
        "/api/feedback",
        json={"search_log_id": log_id, "is_positive": False, "comment": "bad"},
        headers=headers
    )
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_positive"] is False
    assert data["search_log_id"] == log_id
    assert doc_id in data["documents"]
    
    # Verify in DB
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.feedback import SearchFeedback
        fb = db.query(SearchFeedback).filter_by(id=data["id"]).first()
        assert fb is not None
        assert len(fb.documents) == 1
        assert fb.documents[0].id == doc_id
    finally:
        db.close()
