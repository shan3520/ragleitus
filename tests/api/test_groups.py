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
