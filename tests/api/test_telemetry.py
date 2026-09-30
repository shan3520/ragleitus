from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.main import app
from app.services import telemetry
from app.services.llm import Usage
from tests.helpers import login, unique_username


def test_summary_and_events_are_scoped_to_the_caller():
    client = TestClient(app)
    headers, user_id = login(client, unique_username("tele"))
    other_headers, _ = login(client, unique_username("tele_other"))

    session = SessionLocal()
    telemetry.record_llm_call(session, user_id=user_id, operation="chat", provider="openai",
                              model="gpt-4o-mini", latency_ms=120, usage=Usage(100, 50))
    session.commit()
    session.close()

    summary = client.get("/api/telemetry/summary?days=7", headers=headers).json()
    assert summary["requests"] == 1
    assert summary["by_model"][0]["model"] == "gpt-4o-mini"

    events = client.get("/api/telemetry/events", headers=headers).json()
    assert events["total"] == 1
    assert events["items"][0]["latency_ms"] == 120
    assert events["items"][0]["tokens_estimated"] is False

    assert client.get("/api/telemetry/summary", headers=other_headers).json()["requests"] == 0
    assert client.get("/api/telemetry/events", headers=other_headers).json()["total"] == 0
