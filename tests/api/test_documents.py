import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.core.middleware import rate_limiter

def _get_authenticated_client(username: str = "doc_user"):
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    login_resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


def test_document_pdf_extract_endpoint():
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Page 1 text")
    pdf.new_page()
    page = pdf.new_page()
    page.insert_text((72, 72), "Page 3 text")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    client, headers = _get_authenticated_client("extract_user")
    response = client.post(
       "/documents/extract",
       files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
       headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pages"] == [
       {"page_number": 1, "text": "Page 1 text"},
       {"page_number": 3, "text": "Page 3 text"},
    ]


def test_list_and_get_documents_empty():
    client, headers = _get_authenticated_client("empty_user")

    response = client.get("/api/documents", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

    get_resp = client.get("/api/documents/999", headers=headers)
    assert get_resp.status_code == 404


def test_document_extract_unauthenticated():
    rate_limiter.reset()
    client = TestClient(app)
    response = client.post("/documents/extract", files={"file": ("test.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 401


def test_review_document_endpoint():
    from app.services.document_service import create_document_with_chunks
    from app.db.database import get_db
    
    # We need a document to review. 
    # Create one manually in the test database.
    client, headers = _get_authenticated_client("api_review_user")
    
    # Get the db session
    db_gen = get_db()
    session = next(db_gen)
    
    doc = create_document_with_chunks(
        session=session,
        user_id="api_review_user",
        title="To Be Reviewed",
        content="Content to review",
        chunk_contents=[],
    )
    session.commit()
    
    doc_id = doc.id
    
    try:
        # Call the review endpoint
        response = client.post(f"/api/documents/{doc_id}/review", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == doc_id
        assert data["last_reviewed_at"] is not None
        
        # Call it for a non-existent document
        response_404 = client.post("/api/documents/99999/review", headers=headers)
        assert response_404.status_code == 404
        
        # Call it with another user
        other_client, other_headers = _get_authenticated_client("other_user")
        response_other_user = other_client.post(f"/api/documents/{doc_id}/review", headers=other_headers)
        assert response_other_user.status_code == 404
    finally:
        # Cleanup
        try:
            next(db_gen)
        except StopIteration:
            pass
