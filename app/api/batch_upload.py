'''Batch upload endpoint.'''
from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(tags=["batch"])

@router.post("/api/documents/batch-status")
def batch_status(user: User = Depends(get_current_user)):
    return {"status": "idle", "queued": 0}
