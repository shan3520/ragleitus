"""Recording and summarising LLM call telemetry (latency, tokens, cost, errors)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.telemetry_event import TelemetryEvent
from app.services.llm import Usage
from app.services.llm.pricing import estimate_cost_usd
from app.services.token_estimation import estimate_token_count


def record_llm_call(
    session: Session,
    *,
    user_id: int,
    operation: str,
    provider: str,
    model: str,
    latency_ms: float,
    usage: Usage | None = None,
    prompt_text: str = "",
    completion_text: str = "",
    ttft_ms: float | None = None,
    error: Exception | None = None,
    conversation_id: int | None = None,
    message_id: int | None = None,
) -> TelemetryEvent:
    """Store one call. When the provider did not report token usage, counts are
    estimated from the text and the event is flagged as estimated."""
    usage = usage or Usage()
    estimated = False
    prompt_tokens, completion_tokens = usage.prompt_tokens, usage.completion_tokens
    if prompt_tokens is None and prompt_text:
        prompt_tokens, estimated = estimate_token_count(prompt_text), True
    if completion_tokens is None and completion_text:
        completion_tokens, estimated = estimate_token_count(completion_text), True
    final_usage = Usage(prompt_tokens, completion_tokens)

    event = TelemetryEvent(
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        operation=operation,
        provider=provider,
        model=model,
        status="error" if error else "ok",
        error_type=type(error).__name__ if error else None,
        latency_ms=round(latency_ms, 2),
        ttft_ms=round(ttft_ms, 2) if ttft_ms is not None else None,
        prompt_tokens=final_usage.prompt_tokens,
        completion_tokens=final_usage.completion_tokens,
        tokens_estimated=estimated,
        cost_usd=None if error else estimate_cost_usd(model, final_usage),
    )
    session.add(event)
    session.flush()
    return event


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low, high = int(rank), min(int(rank) + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 2)


def _bucket():
    return {"requests": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "latencies": []}


def _finish(bucket: dict) -> dict:
    latencies = bucket.pop("latencies")
    bucket["cost_usd"] = round(bucket["cost_usd"], 6)
    bucket["avg_latency_ms"] = round(sum(latencies) / len(latencies), 2) if latencies else None
    return bucket


def summarize(session: Session, user_id: int, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = (
        session.query(TelemetryEvent)
        .filter(TelemetryEvent.user_id == user_id, TelemetryEvent.created_at >= since)
        .all()
    )

    totals = _bucket()
    by_model: dict[tuple[str, str], dict] = defaultdict(_bucket)
    by_day: dict[str, dict] = defaultdict(_bucket)
    ttfts: list[float] = []
    unpriced = 0

    for event in events:
        day = event.created_at.date().isoformat()
        for bucket in (totals, by_model[(event.provider, event.model)], by_day[day]):
            bucket["requests"] += 1
            bucket["errors"] += event.status == "error"
            bucket["prompt_tokens"] += event.prompt_tokens or 0
            bucket["completion_tokens"] += event.completion_tokens or 0
            bucket["cost_usd"] += event.cost_usd or 0.0
            if event.latency_ms is not None and event.status == "ok":
                bucket["latencies"].append(event.latency_ms)
        if event.ttft_ms is not None:
            ttfts.append(event.ttft_ms)
        if event.status == "ok" and event.cost_usd is None:
            unpriced += 1

    latencies = list(totals["latencies"])
    summary = _finish(totals)
    summary.update(
        {
            "days": days,
            "error_rate": round(summary["errors"] / summary["requests"], 4) if summary["requests"] else 0.0,
            "p50_latency_ms": _percentile(latencies, 0.50),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "p50_ttft_ms": _percentile(ttfts, 0.50),
            # Calls whose model has no entry in the pricing table are not in cost_usd.
            "unpriced_requests": unpriced,
            "by_model": sorted(
                ({"provider": p, "model": m, **_finish(b)} for (p, m), b in by_model.items()),
                key=lambda row: row["requests"],
                reverse=True,
            ),
            "daily": [{"date": d, **_finish(by_day[d])} for d in sorted(by_day)],
        }
    )
    return summary


def list_events(session: Session, user_id: int, limit: int = 50, offset: int = 0) -> tuple[list[TelemetryEvent], int]:
    query = session.query(TelemetryEvent).filter(TelemetryEvent.user_id == user_id)
    total = query.count()
    items = query.order_by(TelemetryEvent.created_at.desc(), TelemetryEvent.id.desc()).offset(offset).limit(limit).all()
    return items, total
