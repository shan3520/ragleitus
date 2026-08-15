from sqlalchemy.orm import Session
from app.models.group import Group
from app.models.document import Document

def create_group(session: Session, name: str) -> Group:
    group = Group(name=name)
    session.add(group)
    session.flush()
    return group

def delete_group(session: Session, group_id: int, hard_delete: bool = False) -> bool:
    group = session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return False
    
    if hard_delete:
        session.query(Document).filter(Document.group_id == group_id).delete(synchronize_session=False)
        
    session.delete(group)
    session.flush()
    return True
