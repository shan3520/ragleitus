"""
Evaluation scoring helpers.

Provides functions to aggregate evaluation scores across experiments
and compute summary metrics (mean, median, min, max, standard deviation).
These are the building blocks for the evaluation dashboard.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class ScoreSummary:
    """Statistical summary of a set of evaluation scores."""

    count: int
    mean: Optional[float]
    median: Optional[float]
    min_score: Optional[float]
    max_score: Optional[float]
    std_dev: Optional[float]


def _median(values: list[float]) -> float:
    """Return the median of a sorted list of floats."""
    n = len(values)
    mid = n // 2
    if n % 2 == 0:
        return (values[mid - 1] + values[mid]) / 2.0
    return values[mid]


def _std_dev(values: list[float], mean: float) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return round(math.sqrt(variance), 4)


def summarize_scores(scores: Sequence[Optional[float]]) -> ScoreSummary:
    """
    Compute a statistical summary over a sequence of scores.

    ``None`` values are excluded from the computation.

    Parameters
    ----------
    scores : Sequence[Optional[float]]
        Raw evaluation scores (may contain ``None``).

    Returns
    -------
    ScoreSummary
    """
    valid = sorted(s for s in scores if s is not None)

    if not valid:
        return ScoreSummary(
            count=0,
            mean=None,
            median=None,
            min_score=None,
            max_score=None,
            std_dev=None,
        )

    mean = round(sum(valid) / len(valid), 4)
    return ScoreSummary(
        count=len(valid),
        mean=mean,
        median=round(_median(valid), 4),
        min_score=round(min(valid), 4),
        max_score=round(max(valid), 4),
        std_dev=_std_dev(valid, mean),
    )


def compare_experiments(
    experiment_scores: dict[str, Sequence[Optional[float]]],
) -> dict[str, ScoreSummary]:
    """
    Summarize scores for multiple experiments side-by-side.

    Parameters
    ----------
    experiment_scores : dict[str, Sequence[Optional[float]]]
        Mapping of experiment name → list of scores.

    Returns
    -------
    dict[str, ScoreSummary]
        Mapping of experiment name → summary.
    """
    return {name: summarize_scores(scores) for name, scores in experiment_scores.items()}
