import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models import Base, Document, Chunk


def setup_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    # Enable SQLite foreign key enforcement for tests
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
    return engine


def test_foreign_keys_and_relationships():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    doc = Document(title="Test Document", content="This is test content")
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
    Session = sessionmaker(bind=engine)
    session = Session()

    bad_chunk = Chunk(content="Bad chunk", sequence_order=1, document_id=9999)
    session.add(bad_chunk)
    with pytest.raises(IntegrityError):
        session.commit()


def test_cascade_delete():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    doc = Document(title="Document to Delete", content="Content")
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
