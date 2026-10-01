import json

from fastapi.testclient import TestClient

from app.api.deps import get_provider_factory
from app.main import app
from app.services.llm import ProviderError, Usage
from tests.fakes import FakeFactory, FakeProvider
from tests.helpers import login, unique_username


def _setup(reply="Annual leave is 25 days [1].", provider: FakeProvider | None = None):
    factory = FakeFactory(provider or FakeProvider(reply=reply, usage=Usage(300, 12)))
    app.dependency_overrides[get_provider_factory] = lambda: factory
    client = TestClient(app)
    headers, user_id = login(client, unique_username("chat"))
    client.post("/api/provider-keys", json={"provider": "openai", "key": "sk-chatkey12345678", "validate": False}, headers=headers)
    upload = client.post(
        "/api/documents",
        files={"file": ("handbook.txt", b"Employees receive 25 days of annual leave per year.", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 202
    conversation = client.post("/api/conversations", json={}, headers=headers).json()
    return client, headers, factory, conversation["id"], upload.json()["id"]


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_streamed_answer_with_sources_citations_and_usage():
    client, headers, factory, conversation_id, doc_id = _setup()

    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "How many days of annual leave do I get?"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    names = [name for name, _ in events]
    assert names[0] == "sources" and names[-2:] == ["citations", "done"]
    assert set(names[1:-2]) == {"token"}

    sources = events[0][1]["sources"]
    assert sources[0]["document_id"] == doc_id
    assert "".join(d["text"] for n, d in events if n == "token") == "Annual leave is 25 days [1]."
    citations = events[-2][1]["citations"]
    assert [(c["number"], c["document_id"], c["document_title"]) for c in citations] == [(1, doc_id, "handbook")]
    done = events[-1][1]
    assert (done["provider"], done["model"], done["prompt_tokens"], done["completion_tokens"]) == ("openai", "gpt-4o-mini", 300, 12)

    # The model received the retrieved passage in its system prompt.
    system_prompt = factory.provider.calls[-1]["messages"][0].content
    assert "Employees receive 25 days of annual leave" in system_prompt

    detail = client.get(f"/api/conversations/{conversation_id}", headers=headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["citations"][0]["document_id"] == doc_id
    assert detail["title"] == "How many days of annual leave do I get?"

    telemetry = client.get("/api/telemetry/summary", headers=headers).json()
    assert telemetry["requests"] == 1
    assert telemetry["prompt_tokens"] == 300


def test_non_streamed_answer():
    client, headers, _, conversation_id, doc_id = _setup()
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "annual leave?", "stream": False},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "Annual leave is 25 days [1]."
    assert body["citations"][0]["document_id"] == doc_id
    assert body["message_id"] > 0
    assert body["sources"][0]["number"] == 1


def test_provider_errors_surface_as_502_or_error_event():
    provider = FakeProvider(error=ProviderError("openai returned HTTP 401: bad key", status_code=401))
    client, headers, _, conversation_id, _ = _setup(provider=provider)

    resp = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "Q", "stream": False}, headers=headers)
    assert resp.status_code == 502
    assert "bad key" in resp.json()["detail"]

    resp = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "Q"}, headers=headers)
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["status_code"] == 401


def test_asking_with_a_provider_that_has_no_key_is_a_400():
    client, headers, factory, conversation_id, _ = _setup()
    resp = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "Q", "provider": "anthropic"}, headers=headers)
    assert resp.status_code == 400
    assert "No API key stored for provider 'anthropic'" in resp.json()["detail"]


def test_conversations_are_private_and_deletable():
    client, headers, _, conversation_id, _ = _setup()
    other_headers, _ = login(client, unique_username("chat_other"))

    assert client.get(f"/api/conversations/{conversation_id}", headers=other_headers).status_code == 404
    assert client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "Q"}, headers=other_headers).status_code == 404
    assert client.get("/api/conversations", headers=other_headers).json() == []

    assert [c["id"] for c in client.get("/api/conversations", headers=headers).json()] == [conversation_id]
    assert client.delete(f"/api/conversations/{conversation_id}", headers=headers).status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}", headers=headers).status_code == 404


def test_unknown_provider_on_create_is_rejected():
    client, headers, _, _, _ = _setup()
    assert client.post("/api/conversations", json={"provider": "acme"}, headers=headers).status_code == 400
