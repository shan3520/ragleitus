from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.services.pdf_extraction import extract_pdf_pages
from app.services import document_service

router = APIRouter()

# Alias for backward compatibility
get_db_session = get_db


@router.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user), session: Session = Depends(get_db)):
    documents = document_service.list_user_documents(session, user["username"])
    return [
        {"id": document.id, "user_id": document.user_id, "title": document.title}
        for document in documents
    ]


@router.post("/documents/extract")
async def extract_document(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    content_bytes = await file.read()
    try:
        pages = extract_pdf_pages(content_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")
    return {"pages": pages}


@router.get("/api/documents/{document_id}")
def get_document(document_id: int, user: dict = Depends(get_current_user), session: Session = Depends(get_db)):
    document = document_service.get_user_document(session, document_id, user["username"])
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
    deleted = document_service.delete_user_document(session, document_id, user["username"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    session.commit()
