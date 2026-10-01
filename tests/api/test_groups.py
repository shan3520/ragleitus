from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.document import Document
from app.models.group import Group
from tests.helpers import login, unique_username


def _client():
    client = TestClient(app)
    headers, user_id = login(client, unique_username("groups"))
    return client, headers, user_id


def test_groups_require_authentication():
    client = TestClient(app)
    assert client.get("/api/groups").status_code == 401
    assert client.post("/api/groups", json={"name": "x"}).status_code == 401


def test_create_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client, headers, user_id = _client()
        response = client.post("/api/groups", json={"name": "New Test Group"}, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Test Group"
        assert "id" in data
        mock_log_audit.assert_called_once_with(action="group_created", user_id=user_id)


def test_delete_group_no_hard_delete():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client, headers, user_id = _client()
        response = client.post("/api/groups", json={"name": "Delete Me Softly"}, headers=headers)
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.assert_called_once_with(action="group_created", user_id=user_id)
        mock_log_audit.reset_mock()

        db = SessionLocal()
        doc = Document(title="Doc 1", group_id=group_id, user_id=user_id)
        db.add(doc)
        db.commit()
        doc_id = doc.id

        response = client.delete(f"/api/groups/{group_id}?hard_delete=false", headers=headers)
        assert response.status_code == 204

        group_in_db = db.query(Group).filter(Group.id == group_id).first()
        assert group_in_db is None

        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is not None
        db.close()
        mock_log_audit.assert_called_once_with(action="group_deleted", user_id=user_id)


def test_delete_group_with_hard_delete():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client, headers, user_id = _client()
        response = client.post("/api/groups", json={"name": "Delete Me Hard"}, headers=headers)
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.reset_mock()

        db = SessionLocal()
        doc = Document(title="Doc 2", group_id=group_id, user_id=user_id)
        db.add(doc)
        db.commit()
        doc_id = doc.id

        response = client.delete(f"/api/groups/{group_id}?hard_delete=true", headers=headers)
        assert response.status_code == 204

        group_in_db = db.query(Group).filter(Group.id == group_id).first()
        assert group_in_db is None

        db.expire_all()
        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is None
        db.close()
        mock_log_audit.assert_called_once_with(action="group_deleted", user_id=user_id)


def test_list_groups():
    client, headers, user_id = _client()

    resp1 = client.post("/api/groups", json={"name": "Group A"}, headers=headers)
    group1_id = resp1.json()["id"]
    resp2 = client.post("/api/groups", json={"name": "Group B"}, headers=headers)
    group2_id = resp2.json()["id"]

    db = SessionLocal()
    db.add(Document(title="Doc 1", group_id=group1_id, user_id=user_id))
    db.add(Document(title="Doc 2", group_id=group1_id, user_id=user_id))
    db.commit()
    db.close()

    response = client.get("/api/groups", headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert {g["id"] for g in data} == {group1_id, group2_id}
    group_a = next(g for g in data if g["id"] == group1_id)
    group_b = next(g for g in data if g["id"] == group2_id)

    assert group_a["name"] == "Group A"
    assert group_a["document_count"] == 2

    assert group_b["name"] == "Group B"
    assert group_b["document_count"] == 0


def test_update_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client, headers, user_id = _client()

        response = client.post("/api/groups", json={"name": "Old Name"}, headers=headers)
        group_id = response.json()["id"]

        response = client.patch(f"/api/groups/{group_id}", json={"name": "New Name"}, headers=headers)
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"
        assert mock_log_audit.call_count == 2
        assert mock_log_audit.call_args_list[0][1] == {"action": "group_created", "user_id": user_id}
        assert mock_log_audit.call_args_list[1][1] == {"action": "group_updated", "user_id": user_id}


def test_update_group_not_found():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client, headers, _ = _client()
        response = client.patch("/api/groups/9999", json={"name": "New Name"}, headers=headers)
        assert response.status_code == 404
        mock_log_audit.assert_not_called()


def test_move_document_to_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client, headers, user_id = _client()
        response = client.post("/api/groups", json={"name": "Target Group"}, headers=headers)
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.reset_mock()

        db = SessionLocal()
        doc = Document(title="Movable Doc", group_id=None, user_id=user_id)
        db.add(doc)
        db.commit()
        doc_id = doc.id

        response = client.post(f"/api/groups/{group_id}/documents/{doc_id}", headers=headers)
        assert response.status_code == 204

        db.expire_all()
        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is not None
        assert doc_in_db.group_id == group_id
        db.close()
        mock_log_audit.assert_called_once_with(action="document_moved", user_id=user_id, document_id=doc_id)


def test_remove_document_from_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client, headers, user_id = _client()
        response = client.post("/api/groups", json={"name": "Source Group"}, headers=headers)
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.reset_mock()

        db = SessionLocal()
        doc = Document(title="Removable Doc", group_id=group_id, user_id=user_id)
        db.add(doc)
        db.commit()
        doc_id = doc.id

        response = client.delete(f"/api/groups/{group_id}/documents/{doc_id}", headers=headers)
        assert response.status_code == 204

        db.expire_all()
        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is not None
        assert doc_in_db.group_id is None
        db.close()
        mock_log_audit.assert_called_once_with(action="document_moved", user_id=user_id, document_id=doc_id)


def test_users_cannot_see_or_change_each_others_groups():
    owner, owner_headers, owner_id = _client()
    intruder, intruder_headers, intruder_id = _client()

    group_id = owner.post("/api/groups", json={"name": "Private"}, headers=owner_headers).json()["id"]

    assert all(g["id"] != group_id for g in intruder.get("/api/groups", headers=intruder_headers).json())
    assert intruder.patch(f"/api/groups/{group_id}", json={"name": "pwned"}, headers=intruder_headers).status_code == 404
    assert intruder.delete(f"/api/groups/{group_id}", headers=intruder_headers).status_code == 404

    db = SessionLocal()
    intruder_doc = Document(title="Intruder doc", user_id=intruder_id)
    owner_doc = Document(title="Owner doc", user_id=owner_id)
    db.add_all([intruder_doc, owner_doc])
    db.commit()

    # Neither another user's document nor another user's group can be the subject of a move.
    assert intruder.post(f"/api/groups/{group_id}/documents/{intruder_doc.id}", headers=intruder_headers).status_code == 404
    assert intruder.post(f"/api/groups/{group_id}/documents/{owner_doc.id}", headers=intruder_headers).status_code == 404

    db.expire_all()
    assert db.get(Group, group_id).name == "Private"
    assert db.get(Document, owner_doc.id).group_id is None
    db.close()
