import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models import Base, Document
from app.models.query_cluster import QueryCluster

def _add_owner(engine):
    """Documents and groups need an owning user (id 1 in these tests)."""
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, username, password_hash, created_at) VALUES (1, 'owner', '!', CURRENT_TIMESTAMP)"))


def setup_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    # Enable SQLite foreign key enforcement for tests
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
    return engine

def test_query_cluster_persistence():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    cluster = QueryCluster(status="open")
    session.add(cluster)
    session.commit()

    assert cluster.id is not None
    
    fetched = session.query(QueryCluster).filter(QueryCluster.id == cluster.id).one()
    assert fetched.status == "open"
    assert fetched.resolved_by_document_id is None
    assert fetched.resolved_at is None

def test_query_cluster_foreign_key():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    doc = Document(user_id=1, title="Resolver Doc", content="Content")
    session.add(doc)
    session.commit()

    now = datetime.now(timezone.utc)
    cluster = QueryCluster(
        status="handled",
        resolved_by_document_id=doc.id,
        resolved_at=now
    )
    session.add(cluster)
    session.commit()

    fetched = session.query(QueryCluster).filter(QueryCluster.id == cluster.id).one()
    assert fetched.resolved_by_document_id == doc.id
    assert fetched.resolved_at.replace(tzinfo=timezone.utc) == now

def test_query_cluster_invalid_foreign_key():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    cluster = QueryCluster(
        status="handled",
        resolved_by_document_id=9999
    )
    session.add(cluster)
    with pytest.raises(IntegrityError):
        session.commit()
