'''Batch upload endpoint.'''
from fastapi import APIRouter, Depends
from app.api.auth import get_current_user

router = APIRouter(tags=["batch"])

@router.post("/api/documents/batch-status")
def batch_status(user: dict = Depends(get_current_user)):
    return {"status": "idle", "queued": 0}
