from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest

from app.core import metrics
from app.main import app
from tests.helpers import login, unique_username


def _value(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_requests_are_counted_by_route_template_not_raw_path():
    client = TestClient(app)
    headers, _ = login(client, unique_username("metrics"))
    route = {"method": "GET", "route": "/api/documents/{document_id}", "status": "404"}
    before = _value("ragforge_http_requests_total", **route)

    client.get("/api/documents/123456", headers=headers)
    client.get("/api/documents/654321", headers=headers)

    assert _value("ragforge_http_requests_total", **route) == before + 2
    assert _value("ragforge_http_requests_total", method="GET", route="/api/documents/123456", status="404") == 0
    assert _value("ragforge_http_request_duration_seconds_count", method="GET", route="/api/documents/{document_id}") >= 2


def test_llm_calls_are_counted_with_tokens_cost_and_bounded_model_labels(monkeypatch):
    labels = {"provider": "openai", "model": "gpt-4o-mini", "operation": "chat"}
    before = _value("ragforge_llm_calls_total", **labels, status="ok")
    tokens_before = _value("ragforge_llm_tokens_total", **labels, kind="prompt")

    metrics.observe_llm_call(
        provider="openai", model="gpt-4o-mini", operation="chat", ok=True, latency_ms=800, ttft_ms=120,
        prompt_tokens=300, completion_tokens=40, cost_usd=0.0001,
    )

    assert _value("ragforge_llm_calls_total", **labels, status="ok") == before + 1
    assert _value("ragforge_llm_tokens_total", **labels, kind="prompt") == tokens_before + 300
    assert _value("ragforge_llm_cost_usd_total", **labels) > 0
    assert _value("ragforge_llm_time_to_first_token_seconds_count", provider="openai") >= 1

    # Self-hosted model names, and names past the limit, are not separate series.
    assert metrics.model_label("custom", "anything-at-all") == "self-hosted"
    monkeypatch.setattr(metrics, "_model_labels", {f"m{i}" for i in range(metrics.MAX_MODEL_LABELS)})
    assert metrics.model_label("openai", "brand-new-model") == "other"
    assert metrics.model_label("openai", "m3") == "m3"


def test_telemetry_records_feed_the_metrics():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base
    from app.services import telemetry
    from app.services.llm import ProviderError, Usage
    from tests.helpers import make_user

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = make_user(session)
    labels = {"provider": "mistral", "model": "mistral-small-latest", "operation": "evaluation"}
    ok_before = _value("ragforge_llm_calls_total", **labels, status="ok")
    error_before = _value("ragforge_llm_calls_total", **labels, status="error")

    telemetry.record_llm_call(session, user_id=user.id, latency_ms=50, usage=Usage(10, 2), **labels)
    telemetry.record_llm_call(session, user_id=user.id, latency_ms=50, error=ProviderError("down", 503), **labels)

    assert _value("ragforge_llm_calls_total", **labels, status="ok") == ok_before + 1
    assert _value("ragforge_llm_calls_total", **labels, status="error") == error_before + 1


def test_the_document_queue_is_read_at_scrape_time():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base
    from app.models.document import Document
    from tests.helpers import make_user

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    user = make_user(session)
    session.add_all([Document(user_id=user.id, title=t, status=s) for t, s in (("a", "pending"), ("b", "pending"), ("c", "ready"))])
    session.commit()

    registry = CollectorRegistry()
    registry.register(metrics.DocumentQueueCollector(factory))
    assert registry.get_sample_value("ragforge_documents_queued", {"status": "pending"}) == 2
    assert registry.get_sample_value("ragforge_documents_queued", {"status": "indexing"}) == 0
    assert b"ragforge_documents_queued" in generate_latest(registry)


def test_metrics_are_not_served_by_the_api_itself():
    # The web app forwards /backend/* to the API; metrics live on METRICS_PORT instead.
    assert TestClient(app).get("/metrics").status_code == 404


def test_the_metrics_server_starts_once_on_its_port(monkeypatch):
    started = []
    monkeypatch.setattr(metrics, "_started_port", None)
    monkeypatch.setattr(metrics, "start_http_server", lambda port, registry=None: started.append(port))
    assert metrics.start_server(0) is False
    assert metrics.start_server(9464) is True
    assert metrics.start_server(9464) is True
    assert started == [9464]
