import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_provider_factory
from app.main import app
from app.services import embedding_service
from app.services.llm import Usage
from tests.fakes import FakeFactory, FakeProvider, FakeProviderEmbedder
from tests.helpers import login, unique_username


class _FakeProviderEmbedder(FakeProviderEmbedder):
    """Takes ProviderEmbedder's arguments, so the real key lookup runs."""

    def __init__(self, provider, api_key, model, base_url=None):
        super().__init__(provider, model)


@pytest.fixture
def client(monkeypatch, vector_stores):
    monkeypatch.setattr(embedding_service, "ProviderEmbedder", _FakeProviderEmbedder)
    return TestClient(app)


def _key(client, headers, provider, key="sk-settingskey12345678"):
    response = client.post("/api/provider-keys", json={"provider": provider, "key": key, "validate": False}, headers=headers)
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _upload(client, headers, name, text):
    response = client.post("/api/documents", files={"file": (name, text.encode(), "text/plain")}, headers=headers)
    assert response.status_code == 202
    return response.json()["id"]


def test_settings_need_a_signed_in_user(client):
    assert client.get("/api/settings/embeddings").status_code == 401
    assert client.put("/api/settings/embeddings", json={"provider": "local"}).status_code == 401
    assert client.post("/api/settings/embeddings/reindex").status_code == 401


def test_choose_a_provider_then_reindex_the_documents_made_with_the_old_model(client):
    headers, _ = login(client, unique_username("emb"))
    first = _upload(client, headers, "a.txt", "Employees receive 25 days of annual leave.")
    second = _upload(client, headers, "b.txt", "Passwords must be rotated every 90 days.")

    settings = client.get("/api/settings/embeddings", headers=headers).json()
    assert settings["provider"] == "local" and settings["outdated"] == 0
    assert settings["documents"] == [{"provider": "local", "model": "fake-hash", "documents": 2}]
    assert client.get(f"/api/documents/{first}", headers=headers).json()["embedding"] == {"provider": "local", "model": "fake-hash"}

    # No key for OpenAI yet.
    refused = client.put("/api/settings/embeddings", json={"provider": "openai"}, headers=headers)
    assert refused.status_code == 400
    assert "No API key stored for OpenAI" in refused.json()["detail"]

    _key(client, headers, "openai")
    saved = client.put("/api/settings/embeddings", json={"provider": "openai"}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert (saved.json()["provider"], saved.json()["model"], saved.json()["outdated"]) == ("openai", "text-embedding-3-small", 2)

    queued = client.post("/api/settings/embeddings/reindex", headers=headers)
    assert queued.status_code == 202
    assert queued.json() == {"queued": 2, "document_ids": [first, second]}

    after = client.get("/api/settings/embeddings", headers=headers).json()
    assert after["outdated"] == 0 and after["indexing"] == 0
    assert after["documents"] == [{"provider": "openai", "model": "text-embedding-3-small", "documents": 2}]
    detail = client.get(f"/api/documents/{second}", headers=headers).json()
    assert detail["status"] == "ready"
    assert detail["embedding"] == {"provider": "openai", "model": "text-embedding-3-small"}
    # Nothing left to do, unless everything is asked for.
    assert client.post("/api/settings/embeddings/reindex", headers=headers).json()["queued"] == 0
    assert client.post("/api/settings/embeddings/reindex", json={"scope": "all"}, headers=headers).json()["queued"] == 2


def test_settings_are_private(client):
    alice, _ = login(client, unique_username("emb"))
    bob, _ = login(client, unique_username("emb"))
    _key(client, alice, "mistral")
    assert client.put("/api/settings/embeddings", json={"provider": "mistral"}, headers=alice).status_code == 200
    mine = _upload(client, alice, "a.txt", "Alice's notes about rockets.")

    assert client.get("/api/settings/embeddings", headers=bob).json()["provider"] == "local"
    assert client.post("/api/settings/embeddings/reindex", json={"scope": "all"}, headers=bob).json()["queued"] == 0
    assert client.get(f"/api/documents/{mine}", headers=alice).json()["embedding"]["provider"] == "mistral"


@pytest.mark.parametrize(
    "payload, status",
    [({"provider": "anthropic"}, 400), ({"provider": "nonsense"}, 400), ({"provider": ""}, 422), ({}, 422)],
)
def test_invalid_choices_are_refused(client, payload, status):
    headers, _ = login(client, unique_username("emb"))
    assert client.put("/api/settings/embeddings", json=payload, headers=headers).status_code == status


def test_chat_says_when_documents_could_only_be_searched_by_keyword(client):
    factory = FakeFactory(FakeProvider(reply="Rotate every 90 days [1].", usage=Usage(10, 5)))
    app.dependency_overrides[get_provider_factory] = lambda: factory
    headers, _ = login(client, unique_username("emb"))
    _key(client, headers, "openai")  # for chat
    mistral = _key(client, headers, "mistral")  # for embeddings
    assert client.put("/api/settings/embeddings", json={"provider": "mistral"}, headers=headers).status_code == 200
    _upload(client, headers, "it.txt", "Passwords must be rotated every 90 days.")
    assert client.delete(f"/api/provider-keys/{mistral}", headers=headers).status_code == 200

    conversation = client.post("/api/conversations", json={}, headers=headers).json()["id"]
    response = client.post(
        f"/api/conversations/{conversation}/messages",
        json={"content": "How often are passwords rotated?", "provider": "openai", "model": "gpt-4o-mini"},
        headers=headers,
    )
    first_event = response.text.split("\n\n")[0]
    assert first_event.startswith("event: sources")
    data = json.loads(first_event.split("data: ", 1)[1])
    assert len(data["sources"]) == 1  # still found, by keyword
    assert data["warnings"] == [
        "1 document embedded with mistral/mistral-embed could only be searched by keyword: "
        "No API key stored for Mistral AI, which your embedding setting uses. "
        "Add the key, or switch embeddings back to the local model in Settings."
    ]
    assert client.get("/api/settings/embeddings", headers=headers).json()["key_missing"] is True
