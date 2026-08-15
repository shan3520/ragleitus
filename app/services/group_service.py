from sqlalchemy.orm import Session
from app.models.group import Group

def create_group(session: Session, name: str) -> Group:
    group = Group(name=name)
    session.add(group)
    session.flush()
    return group
