from fastapi.testclient import TestClient

from app.api.deps import get_provider_factory
from app.db.database import SessionLocal
from app.main import app
from app.models import ProviderKey
from app.services.llm import ProviderError
from tests.fakes import FakeFactory, FakeProvider
from tests.helpers import login, unique_username

VALID_KEY = "sk-testkey1234567"


def _client(factory: FakeFactory | None = None):
    factory = factory or FakeFactory()
    app.dependency_overrides[get_provider_factory] = lambda: factory
    client = TestClient(app)
    headers, user_id = login(client, unique_username("keys"))
    return client, headers, factory


def test_post_provider_key_validates_and_stores_encrypted_value():
    client, headers, factory = _client()

    resp = client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openai"
    assert data["masked_key"] == "sk-***4567"
    assert VALID_KEY not in resp.text
    assert factory.created == [("openai", VALID_KEY, None)]

    session = SessionLocal()
    stored = session.query(ProviderKey).filter_by(id=data["id"]).one()
    assert stored.encrypted_key != VALID_KEY
    assert VALID_KEY not in stored.encrypted_key
    session.close()


def test_legacy_path_still_works():
    client, headers, _ = _client()
    resp = client.post("/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers)
    assert resp.status_code == 200
    assert client.get("/provider-keys", headers=headers).json()[0]["provider"] == "openai"


def test_rejected_key_is_not_stored():
    client, headers, _ = _client(FakeFactory(FakeProvider(error=ProviderError("HTTP 401", status_code=401))))

    resp = client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "OpenAI rejected the key."
    assert client.get("/api/provider-keys", headers=headers).json() == []


def test_unreachable_provider_returns_502():
    client, headers, _ = _client(FakeFactory(FakeProvider(error=ProviderError("Could not reach openai"))))
    resp = client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers)
    assert resp.status_code == 502


def test_validation_can_be_skipped():
    client, headers, factory = _client()
    resp = client.post("/api/provider-keys", json={"provider": "groq", "key": "gsk_x", "validate": False}, headers=headers)
    assert resp.status_code == 200
    assert factory.created == []


def test_unknown_provider_is_rejected():
    client, headers, _ = _client()
    resp = client.post("/api/provider-keys", json={"provider": "acme", "key": "k"}, headers=headers)
    assert resp.status_code == 400


def test_custom_provider_requires_and_stores_base_url():
    client, headers, factory = _client()

    resp = client.post("/api/provider-keys", json={"provider": "custom", "key": "none"}, headers=headers)
    assert resp.status_code == 400

    resp = client.post(
        "/api/provider-keys",
        json={"provider": "custom", "key": "none", "base_url": "http://localhost:11434/v1/"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["base_url"] == "http://localhost:11434/v1"
    assert factory.created[-1] == ("custom", "none", "http://localhost:11434/v1")


def test_saving_again_replaces_the_key():
    client, headers, _ = _client()
    first = client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers).json()
    second = client.post("/api/provider-keys", json={"provider": "openai", "key": "sk-replacement9999"}, headers=headers).json()
    assert first["id"] == second["id"]
    keys = client.get("/api/provider-keys", headers=headers).json()
    assert [k["masked_key"] for k in keys] == ["sk-***9999"]


def test_get_provider_keys_returns_masked_values():
    client, headers, _ = _client()
    created_id = client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers).json()["id"]

    data = client.get("/api/provider-keys", headers=headers).json()
    assert data == [{"id": created_id, "provider": "openai", "masked_key": "sk-***4567", "base_url": None}]


def test_delete_provider_key_removes_key():
    client, headers, _ = _client()
    created_id = client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers).json()["id"]

    resp = client.delete(f"/api/provider-keys/{created_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Provider key deleted"
    assert client.get("/api/provider-keys", headers=headers).json() == []


def test_delete_nonexistent_provider_key_returns_404():
    client, headers, _ = _client()
    resp = client.delete("/api/provider-keys/999", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Provider key not found"


def test_validate_stored_key():
    factory = FakeFactory()
    client, headers, _ = _client(factory)
    client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers)

    resp = client.post("/api/provider-keys/openai/validate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True

    factory.provider.error = ProviderError("HTTP 401", status_code=401)
    assert client.post("/api/provider-keys/openai/validate", headers=headers).json()["valid"] is False

    assert client.post("/api/provider-keys/groq/validate", headers=headers).status_code == 404


def test_list_providers_marks_configured_ones():
    client, headers, _ = _client()
    client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=headers)

    providers = {p["name"]: p for p in client.get("/api/providers", headers=headers).json()}
    assert providers["openai"]["configured"] is True
    assert providers["anthropic"]["configured"] is False
    assert providers["anthropic"]["default_model"] == "claude-opus-5-5"
    assert providers["custom"]["requires_base_url"] is True


def test_users_cannot_see_or_delete_each_others_keys():
    client, owner_headers, _ = _client()
    other_headers, _ = login(client, unique_username("key_other"))

    key_id = client.post("/api/provider-keys", json={"provider": "openai", "key": VALID_KEY}, headers=owner_headers).json()["id"]

    assert client.get("/api/provider-keys", headers=other_headers).json() == []
    assert client.delete(f"/api/provider-keys/{key_id}", headers=other_headers).status_code == 404
    assert client.post("/api/provider-keys/openai/validate", headers=other_headers).status_code == 404
    assert [k["id"] for k in client.get("/api/provider-keys", headers=owner_headers).json()] == [key_id]
