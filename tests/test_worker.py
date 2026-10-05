"""The Celery worker path, run in eager mode (no Redis): uploads go through the task."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import ingestion
from app.worker import celery_app, index_document_task
from tests.helpers import login, unique_username


def test_uploads_are_indexed_through_the_celery_task(monkeypatch):
    ran = []
    original = index_document_task.run

    def recording_run(document_id):
        ran.append(document_id)
        return original(document_id)

    monkeypatch.setattr(ingestion.settings, "task_queue", "celery")
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(index_document_task, "run", recording_run)

    client = TestClient(app)
    headers, _ = login(client, unique_username("worker"))
    doc_id = client.post("/api/documents", files={"file": ("w.txt", b"Queued text.", "text/plain")}, headers=headers).json()["id"]

    assert ran == [doc_id]
    assert client.get(f"/api/documents/{doc_id}", headers=headers).json()["status"] == "ready"


def test_worker_settings_suit_long_jobs():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
