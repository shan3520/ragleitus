from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.models.evaluation import Experiment
from app.services.evaluation_scoring import compare_experiments

router = APIRouter(tags=["evaluations"])


@router.get("/api/evaluations/summary")
def get_evaluation_summary(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Get side-by-side evaluation score summaries for all experiments.
    """
    experiments = session.query(Experiment).all()
    experiment_scores: dict[str, list[float | None]] = {}

    for exp in experiments:
        scores = [eval_obj.score for eval_obj in exp.evaluations]
        experiment_scores[exp.name] = scores

    summaries = compare_experiments(experiment_scores)
    return {
        exp_name: {
            "count": summary.count,
            "mean": summary.mean,
            "median": summary.median,
            "min_score": summary.min_score,
            "max_score": summary.max_score,
            "std_dev": summary.std_dev,
        }
        for exp_name, summary in summaries.items()
    }
