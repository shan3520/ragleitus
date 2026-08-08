import os
import tempfile
from unittest import mock

import fitz
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models import Base, Chunk, Document


def test_document_pdf_e2e_flow():
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_url = f"sqlite:///{tf.name}"
    os.environ["DATABASE_URL"] = db_url

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Page 1 text")
    page = pdf.new_page()
    page.insert_text((72, 72), "Page 2 text")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    client = TestClient(app)
    app.dependency_overrides = {}
    from app.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"username": 1}

    response = client.post(
        "/api/documents",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "sample.pdf"
    assert len(payload["chunks"]) == 1
    assert payload["status"] == "indexed"

    # Duplicate upload should be rejected with 409
    response = client.post(
        "/api/documents",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 409

    document_id = payload["id"]

    response = client.get(f"/api/documents/{document_id}")
    assert response.status_code == 200
    assert response.json()["chunks"] == payload["chunks"]

    session = Session()
    assert session.query(Document).count() == 1
    assert session.query(Chunk).count() == 1
    session.close()

    response = client.delete(f"/api/documents/{document_id}")
    assert response.status_code == 204

    session = Session()
    assert session.query(Document).count() == 0
    assert session.query(Chunk).count() == 0
    session.close()


def test_extraction_failure_rollback():
    """Test that document and chunks are rolled back on extraction failure"""
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_url = f"sqlite:///{tf.name}"
    os.environ["DATABASE_URL"] = db_url

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Test content")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    client = TestClient(app)
    app.dependency_overrides = {}
    from app.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"username": 1}

    # Mock extract_text to raise an exception
    with mock.patch("app.api.documents.extract_text", side_effect=Exception("Extraction failed")):
        response = client.post(
            "/api/documents",
            files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 500
        assert "Failed to extract or process document" in response.json()["detail"]

    # Verify that no documents or chunks were saved
    session = Session()
    assert session.query(Document).count() == 0
    assert session.query(Chunk).count() == 0
    session.close()


def test_successful_chunking_and_status_update():
    """Test that chunks are successfully saved and document status is updated to indexed"""
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_url = f"sqlite:///{tf.name}"
    os.environ["DATABASE_URL"] = db_url

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Test chunk 1")
    page = pdf.new_page()
    page.insert_text((72, 72), "Test chunk 2")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    client = TestClient(app)
    app.dependency_overrides = {}
    from app.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"username": 1}

    response = client.post(
        "/api/documents",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "indexed"
    assert len(payload["chunks"]) >= 1

    # Verify chunks are saved in database
    session = Session()
    document = session.query(Document).filter_by(id=payload["id"]).first()
    assert document is not None
    assert document.status == "indexed"
    assert len(document.chunks) >= 1
    session.close()
