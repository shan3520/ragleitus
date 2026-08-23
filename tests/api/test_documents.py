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


def test_list_documents_sorts_by_negative_impact():
    from app.services.document_service import create_document_with_chunks
    from app.db.database import get_db
    from app.models.document import SearchQueryLog
    from app.models.feedback import SearchFeedback

    client, headers = _get_authenticated_client("impact_sort_user")

    db_gen = get_db()
    session = next(db_gen)

    try:
        doc_ids = {}
        for title, negative_count in [
            ("impact_none", 0),
            ("impact_single", 1),
            ("impact_heavy", 3),
        ]:
            doc = create_document_with_chunks(
                session=session,
                user_id="impact_sort_user",
                title=title,
                content="Impact sorting content",
                chunk_contents=[],
            )
            session.commit()

            for _ in range(negative_count):
                query_log = SearchQueryLog(query_text=f"negative query for {title}")
                session.add(query_log)
                session.flush()
                feedback = SearchFeedback(
                    search_log_id=query_log.id,
                    is_positive=False,
                    documents=[doc],
                )
                session.add(feedback)
            session.commit()
            doc_ids[title] = doc.id

        response = client.get("/api/documents", headers=headers)
        assert response.status_code == 200
        payload = response.json()

        ids = [item["id"] for item in payload]
        scores = [item["negative_impact"] for item in payload]

        assert ids.index(doc_ids["impact_heavy"]) < ids.index(doc_ids["impact_single"])
        assert ids.index(doc_ids["impact_single"]) < ids.index(doc_ids["impact_none"])
        assert scores == sorted(scores, reverse=True)
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass


def test_list_documents_query_count_does_not_scale_with_document_count():
    import uuid

    from sqlalchemy import event

    from app.db.database import engine, get_db
    from app.models.document import SearchQueryLog
    from app.models.feedback import SearchFeedback
    from app.services.document_service import create_document_with_chunks

    run_suffix = uuid.uuid4().hex[:8]
    scaling_user = f"query_scaling_user_{run_suffix}"
    baseline_user = f"query_baseline_user_{run_suffix}"

    client, headers = _get_authenticated_client(scaling_user)
    baseline_client, baseline_headers = _get_authenticated_client(baseline_user)

    db_gen = get_db()
    session = next(db_gen)

    try:
        create_document_with_chunks(
            session=session,
            user_id=baseline_user,
            title="single_doc",
            content="content",
            chunk_contents=[],
        )
        session.commit()

        expected_impacts = {}
        for idx in range(6):
            doc = create_document_with_chunks(
                session=session,
                user_id=scaling_user,
                title=f"scaling_doc_{idx}",
                content="content",
                chunk_contents=[],
            )
            session.flush()
            for _ in range(idx):
                query_log = SearchQueryLog(query_text=f"negative query scaling {idx}")
                session.add(query_log)
                session.flush()
                feedback = SearchFeedback(
                    search_log_id=query_log.id,
                    is_positive=False,
                    documents=[doc],
                )
                session.add(feedback)
            expected_impacts[doc.id] = float(idx)
        session.commit()

        def _count_selects(do_request):
            statements = []

            def _record_select(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)

            event.listen(engine, "before_cursor_execute", _record_select)
            try:
                response = do_request()
                assert response.status_code == 200
                return response.json(), len(statements)
            finally:
                event.remove(engine, "before_cursor_execute", _record_select)

        payload_multi, selects_multi = _count_selects(
            lambda: client.get("/api/documents", headers=headers)
        )
        payload_single, selects_single = _count_selects(
            lambda: baseline_client.get("/api/documents", headers=baseline_headers)
        )

        # N+1 regression guard: serving 6 documents must not cost more queries
        # than serving 1.
        assert selects_multi == selects_single

        assert len(payload_multi) == 6
        by_id = {item["id"]: item for item in payload_multi}
        assert set(by_id) == set(expected_impacts)
        for doc_id, item in by_id.items():
            assert set(item) == {"id", "user_id", "title", "negative_impact"}
            assert item["user_id"] == scaling_user
            assert item["title"].startswith("scaling_doc_")
            assert item["negative_impact"] == expected_impacts[doc_id]

        scores = [item["negative_impact"] for item in payload_multi]
        assert scores == sorted(scores, reverse=True)
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass
