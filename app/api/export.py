"""Export your usage, evaluation and activity numbers."""
import csv
import io
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.sanitization import spreadsheet_safe
from app.db.database import get_db
from app.models.user import User
from app.services import export_service

router = APIRouter(tags=["export"])


@router.get("/api/export/metrics")
def export_metrics(
    days: int = Query(30, ge=1, le=365),
    format: Literal["json", "csv"] = Query("json"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Your LLM usage (totals, per model, per day: calls, errors, tokens, cost,
    latency), evaluation averages and activity counts for the last `days` days.
    `format=csv` gives long-format rows: section, key, metric, value."""
    data = export_service.metrics_export(session, user.id, user.username, days)
    if format == "json":
        return data
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["section", "key", "metric", "value"])
    writer.writeheader()
    # Model names are chosen by users: keep them from running as formulas.
    writer.writerows({k: spreadsheet_safe(v) for k, v in row.items()} for row in export_service.metrics_rows(data))
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ragforge-metrics-{date.today().isoformat()}.csv"'},
    )
