from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models import Chunk, Document
from app.services.pdf_extraction import extract_pdf_pages

router = APIRouter()

# Alias for backward compatibility
get_db_session = get_db


@router.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user), session: Session = Depends(get_db)):
    return [
        {"id": document.id, "user_id": document.user_id, "title": document.title}
        for document in session.query(Document).filter_by(user_id=user["username"]).all()
    ]


@router.post("/documents/extract")
async def extract_document(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    content_bytes = await file.read()
    return {"pages": extract_pdf_pages(content_bytes)}


@router.get("/api/documents/{document_id}")
def get_document(document_id: int, user: dict = Depends(get_current_user), session: Session = Depends(get_db)):
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
def delete_document(document_id: int, user: dict = Depends(get_current_user), session: Session = Depends(get_db)):
    document = session.query(Document).filter_by(id=document_id, user_id=user["username"]).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    session.delete(document)
    session.commit()
