import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.core.middleware import rate_limiter
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

    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.document import SearchQueryLog
        from app.models.feedback import SearchFeedback
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # Create a search log
        log = SearchQueryLog(
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
