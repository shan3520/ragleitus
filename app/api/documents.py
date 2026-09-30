from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services import document_service, group_service, ingestion
from app.services.audit_service import log_audit_event

router = APIRouter(tags=["documents"])

# Alias for backward compatibility
get_db_session = get_db


class DocumentAccepted(BaseModel):
    id: int
    title: str
    filename: str | None
    status: str


def _check_group(session: Session, user: User, group_id: int | None) -> None:
    if group_id is not None and group_service.get_user_group(session, user.id, group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")


def _ingest(
    session: Session,
    user: User,
    file: UploadFile,
    group_id: int | None,
    background_tasks: BackgroundTasks,
    pages: list[ingestion.ExtractedPage] | None = None,
    content: bytes | None = None,
):
    _check_group(session, user, group_id)
    content = content if content is not None else file.file.read()
    try:
        document = ingestion.create_document(session, user.id, file.filename or "upload", content, group_id, pages=pages)
    except ingestion.DuplicateDocumentError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "document_id": exc.existing_id})
    except ingestion.FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except ingestion.IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    session.commit()
    background_tasks.add_task(ingestion.index_document, document.id)
    background_tasks.add_task(log_audit_event, action="document_uploaded", user_id=user.id, document_id=document.id)
    return document


@router.post("/api/documents", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentAccepted)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    group_id: int | None = Form(None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Upload a PDF, Markdown or text file. Indexing runs in the background;
    poll `GET /api/documents/{id}` until `status` is `ready` (or `failed`)."""
    document = _ingest(session, user, file, group_id, background_tasks)
    return DocumentAccepted(id=document.id, title=document.title, filename=document.filename, status=document.status)


@router.get("/api/documents")
def list_documents(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    documents = document_service.list_user_documents(session, user.id)
    items = [
        {
            "id": document.id,
            "user_id": document.user_id,
            "title": document.title,
            "status": document.status,
            "negative_impact": document.negative_impact,
        }
        for document in documents
    ]
    items.sort(key=lambda item: item["negative_impact"], reverse=True)
    return items


@router.post("/documents/extract")
def extract_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    group_id: int | None = Form(None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Legacy upload endpoint: stores and indexes the PDF like `POST /api/documents`,
    and returns the extracted text of each non-empty page."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")
    content = file.file.read()
    try:
        pages = ingestion.extract_pages(file.filename, content)
    except ingestion.IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _ingest(session, user, file, group_id, background_tasks, pages=pages, content=content)
    return {"pages": [{"page_number": p.number, "text": p.text} for p in pages]}


@router.get("/api/documents/{document_id}")
def get_document(document_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    document = document_service.get_user_document(session, document_id, user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": document.id,
        "status": document.status,
        "error": document.error,
        "title": document.title,
        "filename": document.filename,
        "group_id": document.group_id,
        "created_at": document.created_at,
        "chunks": [
            {"id": chunk.id, "sequence_order": chunk.sequence_order, "page_number": chunk.page_number, "content": chunk.content}
            for chunk in sorted(document.chunks, key=lambda c: c.sequence_order)
        ],
    }


@router.post("/api/documents/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentAccepted)
def reindex_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Rebuild a document's chunks and vectors, e.g. after changing chunk settings or the embedding model."""
    document = ingestion.mark_for_reindex(session, user.id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    session.commit()
    background_tasks.add_task(ingestion.index_document, document.id)
    return DocumentAccepted(id=document.id, title=document.title, filename=document.filename, status=document.status)


@router.delete("/api/documents/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not ingestion.delete_document(session, user.id, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    session.commit()
    background_tasks.add_task(log_audit_event, action="document_deleted", user_id=user.id, document_id=document_id)


@router.post("/api/documents/{document_id}/review")
def review_document(document_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    doc = document_service.mark_document_reviewed(session, user.id, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"id": doc.id, "last_reviewed_at": doc.last_reviewed_at}
