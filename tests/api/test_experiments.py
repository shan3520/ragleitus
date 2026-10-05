import csv
import io

from fastapi.testclient import TestClient

from app.api.deps import get_provider_factory
from app.main import app
from tests.fakes import FakeFactory, ScriptedProvider
from tests.helpers import login, unique_username


def _setup():
    provider = ScriptedProvider()
    app.dependency_overrides[get_provider_factory] = lambda: FakeFactory(provider)
    client = TestClient(app)
    headers, _ = login(client, unique_username("exp"))
    client.post("/api/provider-keys", json={"provider": "openai", "key": "sk-expkey12345678", "validate": False}, headers=headers)
    upload = client.post(
        "/api/documents",
        files={"file": ("errors.txt", b"Error E-4711 means the upstream certificate expired.", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 202
    return client, headers, provider


def test_prompt_library_round_trip():
    client, headers, _ = _setup()
    assert client.get("/api/prompts", headers=headers).json() == []
    default = client.get("/api/prompts/default", headers=headers).json()["template"]
    assert "{context}" in default

    bad = client.post("/api/prompts", json={"name": "Bad", "template": "no passages"}, headers=headers)
    assert bad.status_code == 400 and "{context}" in bad.json()["detail"]

    created = client.post("/api/prompts", json={"name": "Brief", "template": "Be brief.\n{context}", "note": "v1"}, headers=headers)
    assert created.status_code == 201
    prompt = created.json()
    assert prompt["latest_version"]["version"] == 1 and len(prompt["versions"]) == 1

    v2 = client.post(f"/api/prompts/{prompt['id']}/versions", json={"template": "Briefer.\n{context}"}, headers=headers)
    assert v2.status_code == 201 and v2.json()["version"] == 2
    renamed = client.patch(f"/api/prompts/{prompt['id']}", json={"name": "Briefest"}, headers=headers).json()
    assert renamed["name"] == "Briefest" and [v["version"] for v in renamed["versions"]] == [2, 1]

    clone = client.post(f"/api/prompts/{prompt['id']}/clone", json={}, headers=headers).json()
    assert clone["name"] == "Briefest (copy)" and clone["latest_version"]["template"] == "Briefer.\n{context}"
    assert [p["name"] for p in client.get("/api/prompts", headers=headers).json()] == ["Briefest", "Briefest (copy)"]

    other, _ = login(client, unique_username("exp"))
    assert client.get(f"/api/prompts/{prompt['id']}", headers=other).status_code == 404
    assert client.post(f"/api/prompts/{prompt['id']}/versions", json={"template": "{context}"}, headers=other).status_code == 404
    assert client.delete(f"/api/prompts/{prompt['id']}", headers=other).status_code == 404

    assert client.delete(f"/api/prompts/{prompt['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/prompts/{prompt['id']}", headers=headers).status_code == 404


def test_chat_answers_with_the_chosen_prompt_until_changed():
    client, headers, provider = _setup()
    prompt = client.post("/api/prompts", json={"name": "Pirate", "template": "Talk like a pirate.\n{context}"}, headers=headers).json()
    version_id = prompt["latest_version"]["id"]
    conversation = client.post("/api/conversations", json={}, headers=headers).json()["id"]

    def ask(**extra):
        body = {"content": "What is E-4711?", "provider": "openai", "model": "gpt-4o-mini", "stream": False, **extra}
        response = client.post(f"/api/conversations/{conversation}/messages", json=body, headers=headers)
        assert response.status_code == 200, response.text
        return provider.calls[-1]["messages"][0].content

    assert ask(prompt_version_id=version_id).startswith("Talk like a pirate.")
    assert ask().startswith("Talk like a pirate.")  # kept for the conversation
    assert client.get(f"/api/conversations/{conversation}", headers=headers).json()["prompt_version_id"] == version_id
    assert ask(prompt_version_id=None).startswith("You are RAGForge")  # back to the built-in prompt

    other, _ = login(client, unique_username("exp"))
    theirs = client.post("/api/conversations", json={}, headers=other).json()["id"]
    client.post("/api/provider-keys", json={"provider": "openai", "key": "sk-expkey12345678", "validate": False}, headers=other)
    stolen = client.post(
        f"/api/conversations/{theirs}/messages",
        json={"content": "Q", "provider": "openai", "stream": False, "prompt_version_id": version_id},
        headers=other,
    )
    assert stolen.status_code == 404


def test_create_run_compare_and_export_an_experiment():
    client, headers, _ = _setup()
    prompt = client.post("/api/prompts", json={"name": "Brief", "template": "Be brief.\n{context}"}, headers=headers).json()
    body = {
        "name": "Built-in vs brief",
        "cases": [{"question": "What does error E-4711 mean?", "reference_answer": "The certificate expired."}],
        "variants": [
            {"label": "Built-in", "provider": "openai", "model": "gpt-4o-mini"},
            {"label": "Brief", "provider": "openai", "model": "gpt-4o-mini",
             "prompt_version_id": prompt["latest_version"]["id"], "retrieval": "keyword", "top_k": 3},
        ],
        "run": True,
    }
    created = client.post("/api/experiments", json=body, headers=headers)
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]

    # TestClient runs the background task before returning.
    detail = client.get(f"/api/experiments/{experiment_id}", headers=headers).json()
    assert detail["status"] == "completed"
    assert detail["progress"] == {"done": 2, "total": 2}
    assert detail["cases"][0]["reference_answer"] == "The certificate expired."

    comparison = client.get(f"/api/experiments/{experiment_id}/compare", headers=headers).json()
    assert [v["label"] for v in comparison["variants"]] == ["Built-in", "Brief"]
    assert comparison["variants"][1]["prompt_label"] == "Brief v1"
    assert comparison["variants"][0]["averages"]["faithfulness"] == 0.9
    answers = comparison["cases"][0]["results"]
    assert all("E-4711" in a["answer"] for a in answers.values())

    exported = client.get(f"/api/experiments/{experiment_id}/export?format=csv", headers=headers)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert 'filename="Built-in-vs-brief.csv"' in exported.headers["content-disposition"]
    assert len(list(csv.DictReader(io.StringIO(exported.text)))) == 2
    as_json = client.get(f"/api/experiments/{experiment_id}/export?format=json", headers=headers)
    assert len(as_json.json()["results"]) == 2

    report = client.get("/api/experiments/report", headers=headers).json()
    assert report["experiments_evaluated"] == 1
    assert report["best_performing"] is None  # the fake judge scores both variants alike
    assert [e["name"] for e in client.get("/api/experiments", headers=headers).json()] == ["Built-in vs brief"]

    # Run again: the results are replaced, not added to.
    rerun = client.post(f"/api/experiments/{experiment_id}/run", headers=headers)
    assert rerun.status_code == 202
    assert client.get(f"/api/experiments/{experiment_id}", headers=headers).json()["progress"]["done"] == 2

    other, _ = login(client, unique_username("exp"))
    for path in ("", "/compare", "/export"):
        assert client.get(f"/api/experiments/{experiment_id}{path}", headers=other).status_code == 404
    assert client.post(f"/api/experiments/{experiment_id}/run", headers=other).status_code == 404
    assert client.get("/api/experiments/report", headers=other).json()["experiments"] == []

    assert client.delete(f"/api/experiments/{experiment_id}", headers=headers).status_code == 204
    assert client.get(f"/api/experiments/{experiment_id}", headers=headers).status_code == 404


def test_invalid_experiments_are_refused():
    client, headers, _ = _setup()
    base = {"name": "x", "cases": [{"question": "Q"}], "variants": [{"provider": "openai"}]}
    assert client.post("/api/experiments", json={**base, "variants": [{"provider": "anthropic"}]}, headers=headers).status_code == 400
    assert client.post("/api/experiments", json={**base, "cases": []}, headers=headers).status_code == 422
    assert client.post("/api/experiments", json={**base, "variants": [{"provider": "openai", "retrieval": "x"}]}, headers=headers).status_code == 422
    assert client.get("/api/experiments/report").status_code == 401
