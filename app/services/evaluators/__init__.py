"""Evaluators: interchangeable ways of scoring an answer.

- builtin: RAGForge's own LLM judge (one call, always available);
- ragas: Ragas metrics, if installed (pip install ".[ragas]");
- deepeval: DeepEval metrics, if installed (pip install ".[deepeval]").

Each takes an EvaluationInput and a JudgeModel (the user's provider and
model) and returns Scores with the same metric names, so chat evaluations
and experiments can use any of them. The Docker image installs both
libraries.
"""

from __future__ import annotations

from app.services.evaluators import builtin, deepeval_evaluator, ragas_evaluator
from app.services.evaluators.base import (
    EvaluationError,
    EvaluationInput,
    EvaluatorUnavailable,
    JudgeError,
    JudgeModel,
    Scores,
)

EVALUATORS = {module.NAME: module for module in (builtin, ragas_evaluator, deepeval_evaluator)}
DEFAULT = builtin.NAME


def available() -> list[dict]:
    """Every evaluator, with whether it can run on this server."""
    return [
        {"name": m.NAME, "label": m.LABEL, "description": m.DESCRIPTION, "available": m.installed()}
        for m in EVALUATORS.values()
    ]


def get(name: str | None):
    """The evaluator module for a name; refuses unknown or uninstalled ones."""
    module = EVALUATORS.get(name or DEFAULT)
    if module is None:
        raise EvaluationError(f"Unknown evaluator '{name}'. Choose one of: {', '.join(EVALUATORS)}.")
    if not module.installed():
        raise EvaluatorUnavailable(f'{module.LABEL} is not installed on this server (pip install ".[{module.NAME}]").')
    return module


__all__ = [
    "DEFAULT", "EVALUATORS", "EvaluationError", "EvaluationInput", "EvaluatorUnavailable", "JudgeError",
    "JudgeModel", "Scores", "available", "get",
]
