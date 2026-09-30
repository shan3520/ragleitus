from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.group import Group
from app.models.document import Document
from app.services.audit_service import log_audit_event


def get_user_group(session: Session, user_id: int, group_id: int) -> Group | None:
    return session.query(Group).filter(Group.id == group_id, Group.user_id == user_id).first()


def get_groups_with_document_count(session: Session, user_id: int):
    return (
        session.query(
            Group.id,
            Group.name,
            func.count(Document.id).label("document_count")
        )
        .outerjoin(Document, Group.id == Document.group_id)
        .filter(Group.user_id == user_id)
        .group_by(Group.id)
        .all()
    )


def create_group(session: Session, user_id: int, name: str, background_tasks: BackgroundTasks) -> Group:
    group = Group(user_id=user_id, name=name)
    session.add(group)
    session.flush()
    background_tasks.add_task(log_audit_event, action="group_created", user_id=user_id)
    return group


def delete_group(session: Session, user_id: int, group_id: int, hard_delete: bool = False, background_tasks: BackgroundTasks = None) -> bool:
    group = get_user_group(session, user_id, group_id)
    if not group:
        return False

    if hard_delete:
        session.query(Document).filter(
            Document.group_id == group_id, Document.user_id == user_id
        ).delete(synchronize_session=False)

    session.delete(group)
    session.flush()
    background_tasks.add_task(log_audit_event, action="group_deleted", user_id=user_id)
    return True


def update_group(session: Session, user_id: int, group_id: int, name: str | None = None, background_tasks: BackgroundTasks = None) -> Group | None:
    group = get_user_group(session, user_id, group_id)
    if not group:
        return None

    if name is not None:
        group.name = name

    session.flush()
    background_tasks.add_task(log_audit_event, action="group_updated", user_id=user_id)
    return group


def move_document(db, user_id: int, document_id: int, target_group_id: int | None, background_tasks: BackgroundTasks):
    """Move one of the user's documents into one of their groups, or out of any group.

    Returns None when either the document or the target group does not
    belong to the user.
    """
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if not document:
        return None
    if target_group_id is not None and get_user_group(db, user_id, target_group_id) is None:
        return None
    document.group_id = target_group_id
    db.commit()
    background_tasks.add_task(log_audit_event, action="document_moved", user_id=user_id, document_id=document_id)
    return document
