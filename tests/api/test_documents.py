import os
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models import Base, Document


def test_get_documents_is_tenant_isolated():
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db_url = f"sqlite:///{tf.name}"

    os.environ["DATABASE_URL"] = db_url

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    session.add_all(
        [
            Document(user_id=1, title="alice-doc"),
            Document(user_id=2, title="bob-doc"),
        ]
    )
    session.commit()
    session.close()

    client = TestClient(app)

    app.dependency_overrides = {}
    from app.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"username": 1}
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert response.json() == [{"id": 1, "user_id": 1, "title": "alice-doc"}]

    app.dependency_overrides[get_current_user] = lambda: {"username": 2}
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert response.json() == [{"id": 2, "user_id": 2, "title": "bob-doc"}]

