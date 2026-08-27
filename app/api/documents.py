from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.services.pdf_extraction import extract_pdf_pages
from app.services import document_service
from app.services.audit_service import log_audit_event

router = APIRouter()

# Alias for backward compatibility
get_db_session = get_db


@router.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user), session: Session = Depends(get_db)):
    documents = document_service.list_user_documents(session, user["username"])
    items = [
        {
            "id": document.id,
            "user_id": document.user_id,
            "title": document.title,
            "negative_impact": document.negative_impact,
        }
        for document in documents
    ]
    items.sort(key=lambda item: item["negative_impact"], reverse=True)
    return items


@router.post("/documents/extract")
async def extract_document(
    file: UploadFile = File(...),
    group_id: int | None = Form(None),
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    content_bytes = await file.read()
    try:
        pages = extract_pdf_pages(content_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")

    chunk_contents = [page["text"] for page in pages]
    document_service.create_document_with_chunks(
        session=session,
        user_id=user["username"],
        title=Path(file.filename).stem,
        content="\n".join(chunk_contents),
        chunk_contents=chunk_contents,
        group_id=group_id,
    )
    session.commit()
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
def delete_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    deleted = document_service.delete_user_document(session, document_id, user["username"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    session.commit()
    background_tasks.add_task(log_audit_event, action="document_deleted", document_id=document_id)


@router.post("/api/documents/{document_id}/review")
def review_document(document_id: int, user: dict = Depends(get_current_user), session: Session = Depends(get_db)):
    doc = document_service.mark_document_reviewed(session, user, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"id": doc.id, "last_reviewed_at": doc.last_reviewed_at}
