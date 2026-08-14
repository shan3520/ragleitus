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
    unique_user = f"eval_user_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique_user)

    db_gen = get_db()
    db = next(db_gen)
    exp_name = f"Exp_{uuid.uuid4().hex[:6]}"
    try:
        exp = Experiment(name=exp_name)
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
