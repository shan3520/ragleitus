import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.core.middleware import rate_limiter
from app.db.database import get_db
from app.models.evaluation import Experiment, Evaluation


def _get_authenticated_client(username: str):
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    login_resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


def test_evaluations_summary_endpoint():
    from tests.helpers import user_id_for

    unique_user = f"eval_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    exp_name = f"Exp_{uuid.uuid4().hex[:6]}"
    try:
        exp = Experiment(name=exp_name, user_id=user_id_for(unique_user))
        db.add(exp)
        db.flush()

        eval1 = Evaluation(experiment_id=exp.id, score=0.85, notes="good")
        eval2 = Evaluation(experiment_id=exp.id, score=0.95, notes="great")
        db.add_all([eval1, eval2])
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/evaluations/summary", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert exp_name in data
    assert data[exp_name]["count"] == 2
    assert data[exp_name]["mean"] == 0.9

    # Another user does not see it.
    _, other_headers = _get_authenticated_client(f"eval_other_{uuid.uuid4().hex[:8]}")
    assert exp_name not in client.get("/api/evaluations/summary", headers=other_headers).json()


def test_evaluate_a_chat_answer_end_to_end():
    from app.api.deps import get_provider_factory
    from tests.fakes import FakeFactory, FakeProvider
    from tests.helpers import login, unique_username

    judge_json = '{"faithfulness": 1, "answer_relevancy": 0.9, "context_precision": 1, "context_recall": null, "rationale": "ok"}'
    provider = FakeProvider(reply="Leave is 25 days [1].")
    app.dependency_overrides[get_provider_factory] = lambda: FakeFactory(provider)
    client = TestClient(app)
    headers, _ = login(client, unique_username("evaluator"))
    client.post("/api/provider-keys", json={"provider": "openai", "key": "sk-evalkey12345678", "validate": False}, headers=headers)
    client.post("/api/documents", files={"file": ("hr.txt", b"Leave is 25 days per year.", "text/plain")}, headers=headers)
    conversation_id = client.post("/api/conversations", json={}, headers=headers).json()["id"]
    answer = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "Leave?", "stream": False}, headers=headers).json()

    provider.reply = judge_json
    resp = client.post("/api/evaluations", json={"message_id": answer["message_id"]}, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["faithfulness"] == 1.0
    assert body["hallucination"] == 0.0
    assert body["context_recall"] is None
    assert body["conversation_id"] == conversation_id

    history = client.get(f"/api/evaluations?conversation_id={conversation_id}", headers=headers).json()
    assert history["total"] == 1
    assert history["averages"]["answer_relevancy"] == 0.9

    other_headers, _ = login(client, unique_username("evaluator_other"))
    assert client.post("/api/evaluations", json={"message_id": answer["message_id"]}, headers=other_headers).status_code == 404
    assert client.get("/api/evaluations", headers=other_headers).json()["total"] == 0
