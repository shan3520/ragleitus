"""Exporting a user's numbers: LLM usage, evaluation scores and activity.

`metrics_export` gathers, for the last `days` days, the telemetry summary
(totals, per model, per day), evaluation averages and counts, and the
conversations started and questions asked; documents and experiments are
counted as they are now, by status. `metrics_rows` flattens
it into long-format rows (section, key, metric, value) for CSV.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.answer_evaluation import AnswerEvaluation
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.experiment import Experiment
from app.services import rag_evaluation, telemetry

USAGE_METRICS = ("requests", "errors", "prompt_tokens", "completion_tokens", "cost_usd", "p50_latency_ms", "p95_latency_ms")


def metrics_export(session: Session, user_id: int, username: str, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    usage = telemetry.summarize(session, user_id, days)

    evaluations = session.query(AnswerEvaluation).filter(
        AnswerEvaluation.user_id == user_id, AnswerEvaluation.created_at >= since
    )
    averages_row = evaluations.with_entities(
        *[func.avg(getattr(AnswerEvaluation, m)) for m in rag_evaluation.METRICS]
    ).one()
    by_evaluator = dict(
        evaluations.with_entities(AnswerEvaluation.evaluator, func.count()).group_by(AnswerEvaluation.evaluator).all()
    )

    documents = dict(
        session.query(Document.status, func.count()).filter(Document.user_id == user_id).group_by(Document.status).all()
    )
    conversations = session.query(func.count(Conversation.id)).filter(
        Conversation.user_id == user_id, Conversation.created_at >= since
    ).scalar()
    questions = (
        session.query(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user_id, Message.role == "user", Message.created_at >= since)
        .scalar()
    )
    experiments = dict(
        session.query(Experiment.status, func.count())
        .filter(Experiment.user_id == user_id, Experiment.cases.isnot(None))
        .group_by(Experiment.status)
        .all()
    )

    return {
        "user": username,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "usage": {
            "totals": {k: usage.get(k) for k in (*USAGE_METRICS, "error_rate", "p50_ttft_ms", "unpriced_requests")},
            "by_model": usage["by_model"],
            "daily": usage["daily"],
        },
        "evaluations": {
            "count": sum(by_evaluator.values()),
            "by_evaluator": by_evaluator,
            "averages": {m: (round(v, 4) if v is not None else None) for m, v in zip(rag_evaluation.METRICS, averages_row)},
        },
        "activity": {
            "documents": {status: documents.get(status, 0) for status in ("pending", "indexing", "ready", "failed")},
            "conversations": conversations,
            "questions": questions,
            "experiments": experiments,
        },
    }


def metrics_rows(data: dict) -> list[dict]:
    """Long-format rows: section, key (a model, a day, a status...), metric, value."""
    rows: list[dict] = []

    def add(section, key, metric, value):
        rows.append({"section": section, "key": key, "metric": metric, "value": value})

    for metric, value in data["usage"]["totals"].items():
        add("usage", "all", metric, value)
    for row in data["usage"]["by_model"]:
        for metric in USAGE_METRICS:
            add("usage_by_model", f"{row['provider']}/{row['model']}", metric, row.get(metric))
    for row in data["usage"]["daily"]:
        for metric in USAGE_METRICS:
            add("usage_by_day", row["date"], metric, row.get(metric))
    add("evaluations", "all", "count", data["evaluations"]["count"])
    for evaluator, count in data["evaluations"]["by_evaluator"].items():
        add("evaluations", evaluator, "count", count)
    for metric, value in data["evaluations"]["averages"].items():
        add("evaluations", "all", f"mean_{metric}", value)
    for status, count in data["activity"]["documents"].items():
        add("documents", status, "count", count)
    add("activity", "all", "conversations", data["activity"]["conversations"])
    add("activity", "all", "questions", data["activity"]["questions"])
    for status, count in data["activity"]["experiments"].items():
        add("experiments", status, "count", count)
    return rows
