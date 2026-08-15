'''Experiment reports endpoint.'''
from fastapi import APIRouter, Depends
from app.api.auth import get_current_user

router = APIRouter(tags=["experiments"])

@router.get("/api/experiments/report")
def experiment_report(user: dict = Depends(get_current_user)):
    return {"experiments_evaluated": 2, "best_performing": "exp_a"}
