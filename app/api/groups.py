from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services import group_service

router = APIRouter()

class GroupCreate(BaseModel):
    name: str

class GroupOut(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)

@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    group_in: GroupCreate,
    session: Session = Depends(get_db)
):
    group = group_service.create_group(session, name=group_in.name)
    session.commit()
    return group

@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int,
    hard_delete: bool = False,
    session: Session = Depends(get_db)
):
    from fastapi import HTTPException
    deleted = group_service.delete_group(session, group_id, hard_delete=hard_delete)
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    session.commit()
    return None
