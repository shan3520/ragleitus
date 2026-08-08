import os

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.auth import get_current_user
from app.models import Chunk, Document

router = APIRouter()


def get_db_session():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./documents.db")
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@router.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user), session=Depends(get_db_session)):
    return [
        {"id": document.id, "user_id": document.user_id, "title": document.title}
        for document in session.query(Document).filter_by(user_id=user["username"]).all()
    ]


@router.post("/api/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), user: dict = Depends(get_current_user), session=Depends(get_db_session)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    content_bytes = await file.read()
    import hashlib
    sha = hashlib.sha256(content_bytes).hexdigest()

    existing = session.query(Document).filter_by(user_id=user["username"], sha256=sha).first()
    if existing:
        raise HTTPException(status_code=409, detail="Document already exists")

    pdf = fitz.open(stream=content_bytes, filetype="pdf")
    page_texts = [page.get_text("text").strip() for page in pdf]
    pdf.close()

    doc = Document(user_id=user["username"], title=file.filename, status="pending", sha256=sha)
    session.add(doc)
    session.commit()
    session.refresh(doc)

    for index, page_text in enumerate(page_texts, start=1):
        if page_text:
            session.add(Chunk(document_id=doc.id, content=page_text, sequence_order=index))
    session.commit()

    session.refresh(doc)
    return {
        "id": doc.id,
        "status": doc.status,
        "title": doc.title,
        "chunks": [{"sequence_order": chunk.sequence_order, "content": chunk.content} for chunk in doc.chunks],
    }


@router.get("/api/documents/{document_id}")
def get_document(document_id: int, user: dict = Depends(get_current_user), session=Depends(get_db_session)):
    document = session.query(Document).filter_by(id=document_id, user_id=user["username"]).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": document.id,
        "status": document.status,
        "title": document.title,
        "chunks": [{"sequence_order": chunk.sequence_order, "content": chunk.content} for chunk in document.chunks],
    }


@router.delete("/api/documents/{document_id}", status_code=204)
def delete_document(document_id: int, user: dict = Depends(get_current_user), session=Depends(get_db_session)):
    document = session.query(Document).filter_by(id=document_id, user_id=user["username"]).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    session.delete(document)
    session.commit()
