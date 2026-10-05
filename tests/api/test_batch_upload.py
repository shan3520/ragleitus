from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import login, unique_username


def test_batch_status_reports_the_users_documents():
    client = TestClient(app)
    headers, _ = login(client, unique_username("batch"))
    ids = [
        client.post("/api/documents", files={"file": (f"{n}.txt", f"Text {n}.".encode(), "text/plain")}, headers=headers).json()["id"]
        for n in ("one", "two")
    ]

    resp = client.post("/api/documents/batch-status", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["ready"] == 2 and body["queued"] == 0 and body["status"] == "idle"
    assert [d["id"] for d in body["documents"]] == ids

    only_first = client.post("/api/documents/batch-status", json={"document_ids": [ids[0]]}, headers=headers).json()
    assert [d["id"] for d in only_first["documents"]] == [ids[0]]

    # Another user sees none of them.
    other, _ = login(client, unique_username("batch_other"))
    assert client.post("/api/documents/batch-status", json={"document_ids": ids}, headers=other).json()["documents"] == []
