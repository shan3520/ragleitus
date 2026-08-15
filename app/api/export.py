'''Export endpoint.'''
from fastapi import APIRouter, Depends
from app.api.auth import get_current_user

router = APIRouter(tags=["export"])

@router.get("/api/export/metrics")
def export_metrics(user: dict = Depends(get_current_user)):
    return {"user": user["username"], "export_status": "completed", "metrics": {"total_queries": 100}}
