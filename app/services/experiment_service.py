"""Score summaries for a user's experiments."""

from sqlalchemy.orm import Session, selectinload

from app.models.evaluation import Experiment
from app.services.evaluation_scoring import ScoreSummary, compare_experiments


def summarize_experiments(session: Session, user_id: int) -> dict[str, ScoreSummary]:
    """Side-by-side score summaries of the user's own experiments, keyed by name."""
    experiments = (
        session.query(Experiment)
        .options(selectinload(Experiment.evaluations))
        .filter(Experiment.user_id == user_id)
        .order_by(Experiment.id)
        .all()
    )
    scores: dict[str, list[float | None]] = {}
    for exp in experiments:
        # Names are not unique; keep each experiment rather than letting a later one replace an earlier one.
        name = exp.name if exp.name not in scores else f"{exp.name} (#{exp.id})"
        scores[name] = [e.score for e in exp.evaluations]
    return compare_experiments(scores)
