import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models import Base, Document, Chunk, Group


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


def test_foreign_keys_and_relationships():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    doc = Document(user_id=1, title="Test Document", content="This is test content")
    chunk1 = Chunk(content="Chunk 1 content", sequence_order=1, document=doc)
    chunk2 = Chunk(content="Chunk 2 content", sequence_order=2, document=doc)
    session.add(doc)
    session.commit()

    assert doc.id is not None
    assert chunk1.id is not None
    assert chunk2.id is not None
    assert chunk1.document_id == doc.id
    assert chunk2.document_id == doc.id

    # Verify relationship traversal
    got_doc = session.query(Document).filter(Document.id == doc.id).one()
    assert len(got_doc.chunks) == 2
    assert got_doc.chunks[0].content == "Chunk 1 content"
    assert got_doc.chunks[1].content == "Chunk 2 content"


def test_fk_enforced():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    bad_chunk = Chunk(content="Bad chunk", sequence_order=1, document_id=9999)
    session.add(bad_chunk)
    with pytest.raises(IntegrityError):
        session.commit()


def test_cascade_delete():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    doc = Document(user_id=1, title="Document to Delete", content="Content")
    chunk1 = Chunk(content="Chunk 1", sequence_order=1, document=doc)
    chunk2 = Chunk(content="Chunk 2", sequence_order=2, document=doc)
    session.add(doc)
    session.commit()

    doc_id = doc.id
    chunk_ids = [chunk1.id, chunk2.id]

    # Delete the document
    session.delete(doc)
    session.commit()

    # Verify document is deleted
    deleted_doc = session.query(Document).filter(Document.id == doc_id).first()
    assert deleted_doc is None

    # Verify chunks are cascaded deleted
    deleted_chunks = session.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
    assert len(deleted_chunks) == 0


def test_group_cascade_set_null():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    group = Group(user_id=1, name="Test Group")
    doc1 = Document(user_id=1, title="Doc 1", content="Content 1", group=group)
    doc2 = Document(user_id=1, title="Doc 2", content="Content 2", group=group)
    session.add(group)
    session.commit()

    group_id = group.id
    doc1_id = doc1.id
    doc2_id = doc2.id

    assert doc1.group_id == group_id
    assert doc2.group_id == group_id

    session.delete(group)
    session.commit()

    deleted_group = session.query(Group).filter(Group.id == group_id).first()
    assert deleted_group is None

    doc1_after = session.query(Document).filter(Document.id == doc1_id).one()
    doc2_after = session.query(Document).filter(Document.id == doc2_id).one()
    
    assert doc1_after.group_id is None
    assert doc2_after.group_id is None


def test_document_review_tracking():
    from datetime import datetime, timezone
    
    engine = setup_engine()
    Base.metadata.create_all(engine)
    _add_owner(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    now = datetime.now(timezone.utc)
    doc = Document(
        user_id=1,
        title="Review Tracking Doc",
        content="Testing review fields",
        last_reviewed_at=now,
        review_status="approved"
    )
    session.add(doc)
    session.commit()

    assert doc.id is not None
    
    fetched_doc = session.query(Document).filter(Document.id == doc.id).one()
    # SQLite returns naive datetime, so we must add utc tzinfo back for comparison
    assert fetched_doc.last_reviewed_at.replace(tzinfo=timezone.utc) == now
    assert fetched_doc.review_status == "approved"
