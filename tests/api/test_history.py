import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.core.middleware import rate_limiter
from app.db.database import get_db


def _get_authenticated_client(username: str):
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "password123"})
    token = client.post("/auth/login", json={"username": username, "password": "password123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


def _insert_audit_logs(entries):
    """entries: list of (action, document_id, timestamp)."""
    db_gen = get_db()
    db = next(db_gen)
    try:
        from app.models.audit_log import AuditLog

        for action, document_id, timestamp in entries:
            db.add(AuditLog(action=action, document_id=document_id, timestamp=timestamp))
        db.commit()
    finally:
        db.close()


def test_history_pagination_offset_slices_records():
    unique = f"pagination_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries = []
    for i in range(1, 9):
        entries.append((unique, i, base + timedelta(minutes=i)))
    _insert_audit_logs(entries)

    resp1 = client.get(f"/api/history?action_type={unique}&limit=3&offset=0", headers=headers)
    assert resp1.status_code == 200
    page1 = resp1.json()
    assert page1["total"] == 8
    assert [item["document_id"] for item in page1["items"]] == [8, 7, 6]

    resp2 = client.get(f"/api/history?action_type={unique}&limit=3&offset=3", headers=headers)
    assert resp2.status_code == 200
    page2 = resp2.json()
    # The second page must be distinct records that were skipped by offset 3
    assert [item["document_id"] for item in page2["items"]] == [5, 4, 3]
    assert page1["items"][0]["id"] != page2["items"][0]["id"]


def test_history_returns_newest_first():
    unique = f"ordering_{uuid.uuid4().hex[:8]}"
    client, headers = _get_authenticated_client(unique)

    base = datetime(2026, 2, 1, tzinfo=timezone.utc)
    entries = [
        (unique, 1, base),
        (unique, 2, base + timedelta(minutes=30)),
        (unique, 3, base + timedelta(minutes=60)),
        (unique, 4, base + timedelta(minutes=90)),
    ]
    _insert_audit_logs(entries)

    resp = client.get(f"/api/history?action_type={unique}&limit=10", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    doc_ids = [item["document_id"] for item in data["items"]]

    assert doc_ids.index(4) < doc_ids.index(3) < doc_ids.index(2) < doc_ids.index(1)


def test_history_filters_by_action_type():
    unique = f"filter_{uuid.uuid4().hex[:8]}"
    deleted = f"{unique}_deleted"
    uploaded = f"{unique}_uploaded"
    moved = f"{unique}_moved"
    client, headers = _get_authenticated_client(unique)

    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    entries = [
        (deleted, 101, base),
        (uploaded, 102, base + timedelta(minutes=1)),
        (deleted, 103, base + timedelta(minutes=2)),
        (moved, 104, base + timedelta(minutes=3)),
    ]
    _insert_audit_logs(entries)

    resp = client.get(f"/api/history?action_type={deleted}&limit=10", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    for item in data["items"]:
        assert item["action"] == deleted

    deleted_ids = {item["document_id"] for item in data["items"]}
    assert 101 in deleted_ids
    assert 103 in deleted_ids
    assert 102 not in deleted_ids
    assert 104 not in deleted_ids


def test_history_filters_by_document_id():
    unique = f"docfilter_{uuid.uuid4().hex[:8]}"
    doc_id = 2000 + (uuid.uuid4().int % 100000)
    client, headers = _get_authenticated_client(unique)

    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    entries = [
        (unique, doc_id, base),
        (unique, doc_id + 1, base + timedelta(minutes=1)),
        (unique, doc_id, base + timedelta(minutes=2)),
    ]
    _insert_audit_logs(entries)

    resp = client.get(f"/api/history?entity_id={doc_id}&action_type={unique}&limit=10", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    for item in data["items"]:
        assert item["document_id"] == doc_id
    assert data["total"] == 2
