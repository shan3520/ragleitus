from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.document import Document
from app.models.group import Group

def test_create_group():
    client = TestClient(app)
    response = client.post("/api/groups", json={"name": "New Test Group"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Test Group"
    assert "id" in data

def test_delete_group_no_hard_delete():
    client = TestClient(app)
    response = client.post("/api/groups", json={"name": "Delete Me Softly"})
    assert response.status_code == 201
    group_id = response.json()["id"]
    
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

def test_delete_group_with_hard_delete():
    client = TestClient(app)
    response = client.post("/api/groups", json={"name": "Delete Me Hard"})
    assert response.status_code == 201
    group_id = response.json()["id"]
    
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
    client = TestClient(app)
    
    # Create group
    response = client.post("/api/groups", json={"name": "Old Name"})
    group_id = response.json()["id"]

    # Update group
    response = client.patch(f"/api/groups/{group_id}", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"

def test_update_group_not_found():
    client = TestClient(app)
    response = client.patch("/api/groups/9999", json={"name": "New Name"})
    assert response.status_code == 404
