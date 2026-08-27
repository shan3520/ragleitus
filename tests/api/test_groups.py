from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.document import Document
from app.models.group import Group

def test_create_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client = TestClient(app)
        response = client.post("/api/groups", json={"name": "New Test Group"})
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Test Group"
        assert "id" in data
        mock_log_audit.assert_called_once_with(action="group_created")

def test_delete_group_no_hard_delete():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client = TestClient(app)
        response = client.post("/api/groups", json={"name": "Delete Me Softly"})
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.assert_called_once_with(action="group_created")
        mock_log_audit.reset_mock()
        
        db = SessionLocal()
        doc = Document(title="Doc 1", group_id=group_id)
        db.add(doc)
        db.commit()
        doc_id = doc.id
        
        response = client.delete(f"/api/groups/{group_id}?hard_delete=false")
        assert response.status_code == 204
        
        group_in_db = db.query(Group).filter(Group.id == group_id).first()
        assert group_in_db is None
        
        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is not None
        db.close()
        mock_log_audit.assert_called_once_with(action="group_deleted")

def test_delete_group_with_hard_delete():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client = TestClient(app)
        response = client.post("/api/groups", json={"name": "Delete Me Hard"})
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.reset_mock()
        
        db = SessionLocal()
        doc = Document(title="Doc 2", group_id=group_id)
        db.add(doc)
        db.commit()
        doc_id = doc.id
        
        response = client.delete(f"/api/groups/{group_id}?hard_delete=true")
        assert response.status_code == 204
        
        group_in_db = db.query(Group).filter(Group.id == group_id).first()
        assert group_in_db is None
        
        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is None
        db.close()
        mock_log_audit.assert_called_once_with(action="group_deleted")

def test_list_groups():
    client = TestClient(app)
    
    # Create two groups
    resp1 = client.post("/api/groups", json={"name": "Group A"})
    group1_id = resp1.json()["id"]
    resp2 = client.post("/api/groups", json={"name": "Group B"})
    group2_id = resp2.json()["id"]
    
    # Add documents to Group A
    db = SessionLocal()
    db.add(Document(title="Doc 1", group_id=group1_id))
    db.add(Document(title="Doc 2", group_id=group1_id))
    db.commit()
    db.close()
    
    # Fetch list
    response = client.get("/api/groups")
    assert response.status_code == 200
    data = response.json()
    
    # Verify groups and counts
    group_a = next(g for g in data if g["id"] == group1_id)
    group_b = next(g for g in data if g["id"] == group2_id)
    
    assert group_a["name"] == "Group A"
    assert group_a["document_count"] == 2
    
    assert group_b["name"] == "Group B"
    assert group_b["document_count"] == 0

def test_update_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client = TestClient(app)
        
        # Create group
        response = client.post("/api/groups", json={"name": "Old Name"})
        group_id = response.json()["id"]
        
        # Update group
        response = client.patch(f"/api/groups/{group_id}", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"
        assert mock_log_audit.call_count == 2
        assert mock_log_audit.call_args_list[0][1] == {"action": "group_created"}
        assert mock_log_audit.call_args_list[1][1] == {"action": "group_updated"}

def test_update_group_not_found():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client = TestClient(app)
        response = client.patch("/api/groups/9999", json={"name": "New Name"})
        assert response.status_code == 404
        mock_log_audit.assert_not_called()

def test_move_document_to_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client = TestClient(app)
        response = client.post("/api/groups", json={"name": "Target Group"})
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.assert_called_once_with(action="group_created")
        mock_log_audit.reset_mock()
        
        db = SessionLocal()
        doc = Document(title="Movable Doc", group_id=None)
        db.add(doc)
        db.commit()
        doc_id = doc.id
        
        response = client.post(f"/api/groups/{group_id}/documents/{doc_id}")
        assert response.status_code == 204
        
        db.expire_all()
        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is not None
        assert doc_in_db.group_id == group_id
        db.close()
        mock_log_audit.assert_called_once_with(action="document_moved", document_id=doc_id)

def test_remove_document_from_group():
    with patch("app.services.group_service.log_audit_event") as mock_log_audit:
        client = TestClient(app)
        response = client.post("/api/groups", json={"name": "Source Group"})
        assert response.status_code == 201
        group_id = response.json()["id"]
        mock_log_audit.assert_called_once_with(action="group_created")
        mock_log_audit.reset_mock()
        
        db = SessionLocal()
        doc = Document(title="Removable Doc", group_id=group_id)
        db.add(doc)
        db.commit()
        doc_id = doc.id
        
        response = client.delete(f"/api/groups/{group_id}/documents/{doc_id}")
        assert response.status_code == 204
        
        db.expire_all()
        doc_in_db = db.query(Document).filter(Document.id == doc_id).first()
        assert doc_in_db is not None
        assert doc_in_db.group_id is None
        db.close()
        mock_log_audit.assert_called_once_with(action="document_moved", document_id=doc_id)