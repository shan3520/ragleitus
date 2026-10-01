from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.telemetry_event import TelemetryEvent
from app.services import telemetry
from app.services.llm import Usage
from tests.helpers import make_user


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def test_record_prices_known_models(session):
    user = make_user(session)
    event = telemetry.record_llm_call(
        session, user_id=user.id, operation="chat", provider="anthropic", model="claude-opus-5-5",
        latency_ms=1234.567, usage=Usage(1000, 500),
    )
    assert event.status == "ok"
    assert event.latency_ms == 1234.57
    assert event.tokens_estimated is False
    assert event.cost_usd == pytest.approx((1000 * 4 + 500 * 20) / 1e6)


def test_missing_usage_is_estimated_and_flagged(session):
    user = make_user(session)
    event = telemetry.record_llm_call(
        session, user_id=user.id, operation="chat", provider="custom", model="llama3",
        latency_ms=10, prompt_text="one two three four", completion_text="five six",
    )
    assert event.prompt_tokens == 5
    assert event.completion_tokens == 2
    assert event.tokens_estimated is True
    assert event.cost_usd is None


def test_errors_are_recorded_without_cost(session):
    user = make_user(session)
    event = telemetry.record_llm_call(
        session, user_id=user.id, operation="chat", provider="openai", model="gpt-4o-mini",
        latency_ms=50, usage=Usage(10, 0), error=TimeoutError("slow"),
    )
    assert (event.status, event.error_type, event.cost_usd) == ("error", "TimeoutError", None)


def test_summary_aggregates_per_user_model_and_day(session):
    alice, bob = make_user(session), make_user(session)
    for latency in (100, 200, 300, 400):
        telemetry.record_llm_call(session, user_id=alice.id, operation="chat", provider="openai",
                                  model="gpt-4o-mini", latency_ms=latency, usage=Usage(1000, 1000), ttft_ms=latency / 2)
    telemetry.record_llm_call(session, user_id=alice.id, operation="chat", provider="groq",
                              model="unknown-model", latency_ms=50, usage=Usage(10, 10))
    telemetry.record_llm_call(session, user_id=alice.id, operation="chat", provider="openai",
                              model="gpt-4o-mini", latency_ms=9999, error=RuntimeError("x"))
    telemetry.record_llm_call(session, user_id=bob.id, operation="chat", provider="openai",
                              model="gpt-4o-mini", latency_ms=1, usage=Usage(1, 1))
    old = telemetry.record_llm_call(session, user_id=alice.id, operation="chat", provider="openai",
                                    model="gpt-4o-mini", latency_ms=1, usage=Usage(1, 1))
    old.created_at = datetime.now(timezone.utc) - timedelta(days=40)
    session.flush()

    summary = telemetry.summarize(session, alice.id, days=30)
    assert summary["requests"] == 6
    assert summary["errors"] == 1
    assert summary["error_rate"] == round(1 / 6, 4)
    assert summary["prompt_tokens"] == 4010
    # Failed calls are left out of latency percentiles.
    assert summary["p50_latency_ms"] == 200.0  # of 50, 100, 200, 300, 400
    assert summary["p95_latency_ms"] == pytest.approx(380.0)
    assert summary["p50_ttft_ms"] == 125.0
    assert summary["cost_usd"] == pytest.approx(4 * (1000 * 0.15 + 1000 * 0.60) / 1e6)
    assert summary["unpriced_requests"] == 1
    top = summary["by_model"][0]
    assert (top["provider"], top["model"], top["requests"], top["errors"]) == ("openai", "gpt-4o-mini", 5, 1)
    assert len(summary["daily"]) == 1


def test_summary_of_nothing(session):
    user = make_user(session)
    summary = telemetry.summarize(session, user.id)
    assert summary["requests"] == 0
    assert summary["p50_latency_ms"] is None
    assert summary["by_model"] == []


def test_list_events_newest_first(session):
    user = make_user(session)
    first = telemetry.record_llm_call(session, user_id=user.id, operation="chat", provider="p", model="m", latency_ms=1)
    second = telemetry.record_llm_call(session, user_id=user.id, operation="chat", provider="p", model="m", latency_ms=2)
    items, total = telemetry.list_events(session, user.id, limit=1)
    assert total == 2
    assert [e.id for e in items] == [second.id]
    assert session.query(TelemetryEvent).count() == 2 and first.id != second.id
