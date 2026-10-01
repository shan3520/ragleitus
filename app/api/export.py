'''Export endpoint.'''
from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(tags=["export"])

@router.get("/api/export/metrics")
def export_metrics(user: User = Depends(get_current_user)):
    return {"user": user.username, "export_status": "completed", "metrics": {"total_queries": 100}}
