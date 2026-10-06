import csv
import io

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import login, unique_username


def test_export_metrics_as_json_and_csv():
    client = TestClient(app)
    assert client.get("/api/export/metrics").status_code == 401
    headers, _ = login(client, unique_username("export"))
    client.post("/api/documents", files={"file": ("a.txt", b"Some text.", "text/plain")}, headers=headers)

    data = client.get("/api/export/metrics?days=7", headers=headers).json()
    assert data["days"] == 7
    assert set(data) >= {"user", "generated_at", "usage", "evaluations", "activity"}
    assert data["activity"]["documents"]["ready"] == 1

    response = client.get("/api/export/metrics?format=csv", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="ragforge-metrics-' in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert {"section": "documents", "key": "ready", "metric": "count", "value": "1"} in rows

    assert client.get("/api/export/metrics?format=xml", headers=headers).status_code == 422
    assert client.get("/api/export/metrics?days=0", headers=headers).status_code == 422


def test_user_chosen_model_names_cannot_run_as_formulas():
    from app.api.deps import get_provider_factory
    from tests.fakes import FakeFactory, FakeProvider

    app.dependency_overrides[get_provider_factory] = lambda: FakeFactory(FakeProvider(reply="Hi."))
    client = TestClient(app)
    headers, _ = login(client, unique_username("export"))
    client.post("/api/provider-keys", json={"provider": "openai", "key": "sk-exportkey12345678", "validate": False}, headers=headers)
    conversation = client.post("/api/conversations", json={}, headers=headers).json()["id"]
    client.post(
        f"/api/conversations/{conversation}/messages",
        json={"content": "Q", "provider": "openai", "model": "=cmd|' /C calc'!A0", "stream": False},
        headers=headers,
    )
    text = client.get("/api/export/metrics?format=csv", headers=headers).text
    assert "openai/=cmd" in text  # inside the key, after the provider: not a formula
    rows = list(csv.DictReader(io.StringIO(text)))
    assert not any(str(v).startswith("=") for row in rows for v in row.values())
