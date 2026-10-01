'''Experiment reports endpoint.'''
from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(tags=["experiments"])

@router.get("/api/experiments/report")
def experiment_report(user: User = Depends(get_current_user)):
    return {"experiments_evaluated": 2, "best_performing": "exp_a"}
