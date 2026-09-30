from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services import group_service

router = APIRouter(tags=["groups"], dependencies=[Depends(get_current_user)])

class GroupCreate(BaseModel):
    name: str

class GroupOut(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)

class GroupUpdate(BaseModel):
    name: str | None = None

class GroupWithCount(GroupOut):
    document_count: int

@router.get("", response_model=list[GroupWithCount])
def list_groups(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return group_service.get_groups_with_document_count(session, user.id)

@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    group_in: GroupCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = group_service.create_group(session, user.id, name=group_in.name, background_tasks=background_tasks)
    session.commit()
    return group

@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int,
    background_tasks: BackgroundTasks,
    hard_delete: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deleted = group_service.delete_group(session, user.id, group_id, hard_delete=hard_delete, background_tasks=background_tasks)
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    session.commit()
    return None

@router.patch("/{group_id}", response_model=GroupOut)
def update_group(
    group_id: int,
    group_in: GroupUpdate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    group = group_service.update_group(session, user.id, group_id, name=group_in.name, background_tasks=background_tasks)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    session.commit()
    return group

@router.post("/{group_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def move_document_to_group(
    group_id: int,
    document_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = group_service.move_document(session, user.id, document_id, target_group_id=group_id, background_tasks=background_tasks)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return None

@router.delete("/{group_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document_from_group(
    group_id: int,
    document_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = group_service.move_document(session, user.id, document_id, target_group_id=None, background_tasks=background_tasks)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return None
