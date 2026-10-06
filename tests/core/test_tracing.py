import base64

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import tracing
from app.core.config import settings


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    tracing.setup_tracing("test", extra_exporters=[exporter])
    yield exporter
    exporter.clear()


def test_tracing_is_off_unless_configured(monkeypatch):
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    monkeypatch.setattr(settings, "langfuse_public_key", settings.langfuse_public_key.__class__(""))
    assert tracing.exporters() == []
    assert tracing.setup_tracing("test") is False


def test_otlp_and_langfuse_exporters_are_configured_without_leaking_keys(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "http://jaeger:4318/")
    monkeypatch.setattr(settings, "langfuse_public_key", SecretStr("pk-lf-123"))
    monkeypatch.setattr(settings, "langfuse_secret_key", SecretStr("sk-lf-456"))
    monkeypatch.setattr(settings, "langfuse_host", "https://langfuse.example.com/")

    (otlp, otlp_headers), (langfuse, langfuse_headers) = tracing.exporter_targets()
    assert (otlp, otlp_headers) == ("http://jaeger:4318/v1/traces", {})
    assert langfuse == "https://langfuse.example.com/api/public/otel/v1/traces"
    assert langfuse_headers == {"Authorization": "Basic " + base64.b64encode(b"pk-lf-123:sk-lf-456").decode()}
    assert len(tracing.exporters()) == 2


def test_a_chat_turn_is_traced_without_its_text_by_default(spans, monkeypatch):
    from app.api.deps import get_provider_factory
    from app.main import app
    from tests.fakes import FakeFactory, FakeProvider
    from tests.helpers import login, unique_username

    monkeypatch.setattr(settings, "trace_content", False)
    app.dependency_overrides[get_provider_factory] = lambda: FakeFactory(FakeProvider(reply="Leave is 25 days [1]."))
    client = TestClient(app)
    headers, user_id = login(client, unique_username("trace"))
    client.post("/api/provider-keys", json={"provider": "openai", "key": "sk-tracekey12345678", "validate": False}, headers=headers)
    client.post("/api/documents", files={"file": ("hr.txt", b"Employees get 25 days of leave.", "text/plain")}, headers=headers)
    spans.clear()
    conversation = client.post("/api/conversations", json={}, headers=headers).json()["id"]
    response = client.post(
        f"/api/conversations/{conversation}/messages",
        json={"content": "How much leave?", "provider": "openai", "model": "gpt-4o-mini", "stream": False},
        headers=headers,
    )
    assert response.status_code == 200

    finished = {s.name: s for s in spans.get_finished_spans()}
    retrieve, generate = finished["rag.retrieve"], finished["rag.generate"]
    assert retrieve.attributes["retrieval.strategy"] == "hybrid" and retrieve.attributes["retrieval.results"] == 1
    assert generate.attributes["gen_ai.system"] == "openai"
    assert generate.attributes["gen_ai.request.model"] == "gpt-4o-mini"
    assert generate.attributes["gen_ai.usage.input_tokens"] == 100
    assert generate.attributes["user.id"] == str(user_id)
    assert generate.attributes["session.id"] == str(conversation)
    assert "gen_ai.prompt" not in generate.attributes and "gen_ai.completion" not in generate.attributes
    assert all("sk-tracekey" not in str(dict(s.attributes)) for s in spans.get_finished_spans())


def test_text_is_traced_only_when_asked(spans, monkeypatch):
    monkeypatch.setattr(settings, "trace_content", True)
    with tracing.span("rag.generate") as current:
        tracing.record_content(current, prompt="the prompt", completion="the answer")
    span = spans.get_finished_spans()[-1]
    assert span.attributes["gen_ai.prompt"] == "the prompt"
    assert span.attributes["gen_ai.completion"] == "the answer"


def test_indexing_and_evaluation_are_traced(spans, tmp_path):
    import asyncio

    from qdrant_client import QdrantClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base
    from app.models.conversation import Conversation, Message
    from app.services import ingestion, rag_evaluation
    from app.services.embeddings import FakeEmbedder
    from app.services.provider_key import encrypt_key, save_provider_key
    from app.services.vector_store import VectorStore
    from tests.fakes import FakeFactory, ScriptedProvider
    from tests.helpers import make_user

    engine = create_engine(f"sqlite:///{tmp_path / 'trace.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    user = make_user(session)
    save_provider_key(session, user.id, "openai", encrypt_key("sk-test-12345678"))
    session.commit()
    doc = ingestion.create_document(session, user.id, "a.txt", b"Leave is 25 days.")
    session.commit()
    embedder = FakeEmbedder()
    ingestion.index_document(
        doc.id, session_factory=factory, embedder=embedder,
        store=VectorStore(QdrantClient(location=":memory:"), embedder.model_name, embedder.dimension),
    )
    conversation = Conversation(user_id=user.id, title="t")
    session.add(conversation)
    session.flush()
    session.add(Message(conversation_id=conversation.id, role="user", content="Leave?"))
    answer = Message(conversation_id=conversation.id, role="assistant", content="25 days [1].", provider="openai",
                     model="gpt-4o-mini", context=[{"number": 1, "content": "Leave is 25 days."}])
    session.add(answer)
    session.commit()
    asyncio.run(rag_evaluation.evaluate_message(session, user.id, answer.id, factory=FakeFactory(ScriptedProvider())))

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert finished["index.document"].attributes["index.outcome"] == "ready"
    assert finished["rag.evaluate"].attributes["evaluation.evaluator"] == "builtin"
    assert finished["rag.evaluate"].attributes["evaluation.faithfulness"] == 0.9
