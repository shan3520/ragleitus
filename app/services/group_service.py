from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.group import Group
from app.models.document import Document
from app.services.audit_service import log_audit_event

def get_groups_with_document_count(session: Session):
    return (
        session.query(
            Group.id, 
            Group.name, 
            func.count(Document.id).label("document_count")
        )
        .outerjoin(Document, Group.id == Document.group_id)
        .group_by(Group.id)
        .all()
    )

def create_group(session: Session, name: str, background_tasks: BackgroundTasks) -> Group:
    group = Group(name=name)
    session.add(group)
    session.flush()
    background_tasks.add_task(log_audit_event, action="group_created")
    return group

def delete_group(session: Session, group_id: int, hard_delete: bool = False, background_tasks: BackgroundTasks = None) -> bool:
    group = session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return False
    
    if hard_delete:
        session.query(Document).filter(Document.group_id == group_id).delete(synchronize_session=False)
        
    session.delete(group)
    session.flush()
    background_tasks.add_task(log_audit_event, action="group_deleted")
    return True

def update_group(session: Session, group_id: int, name: str | None = None, background_tasks: BackgroundTasks = None) -> Group | None:
    group = session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return None
    
    if name is not None:
        group.name = name
        
    session.flush()
    background_tasks.add_task(log_audit_event, action="group_updated")
    return group

def move_document(db, document_id: int, target_group_id: int | None, background_tasks: BackgroundTasks):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        return None
    document.group_id = target_group_id
    db.commit()
    background_tasks.add_task(log_audit_event, action="document_moved", document_id=document_id)
    return document
