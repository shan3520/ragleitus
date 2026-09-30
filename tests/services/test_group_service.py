import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.document import Document
from app.models.group import Group
from app.services import group_service
from tests.helpers import make_user


class _RecordingStore:
    def __init__(self):
        self.deleted: list[tuple[int, list[int]]] = []

    def delete_documents(self, user_id, document_ids):
        self.deleted.append((user_id, sorted(document_ids)))


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    store = _RecordingStore()
    monkeypatch.setattr(group_service, "get_vector_store", lambda: store)
    alice, bob = make_user(session), make_user(session)
    session.commit()
    yield session, alice.id, bob.id, store
    session.close()


def _doc(session, user_id, group_id=None, title="doc"):
    doc = Document(user_id=user_id, title=title, group_id=group_id)
    session.add(doc)
    session.flush()
    return doc


def test_groups_are_private(env):
    session, alice, bob, _ = env
    group = group_service.create_group(session, alice, "Legal", BackgroundTasks())
    assert group_service.get_user_group(session, alice, group.id) is group
    assert group_service.get_user_group(session, bob, group.id) is None
    assert group_service.update_group(session, bob, group.id, "Mine now", BackgroundTasks()) is None
    assert group_service.delete_group(session, bob, group.id, background_tasks=BackgroundTasks()) is False
    assert session.get(Group, group.id).name == "Legal"


def test_document_counts_per_group(env):
    session, alice, bob, _ = env
    legal = group_service.create_group(session, alice, "Legal", BackgroundTasks())
    group_service.create_group(session, alice, "Empty", BackgroundTasks())
    _doc(session, alice, legal.id)
    _doc(session, alice, legal.id)
    counts = {name: n for _, name, n in group_service.get_groups_with_document_count(session, alice)}
    assert counts == {"Legal": 2, "Empty": 0}
    assert group_service.get_groups_with_document_count(session, bob) == []


def test_hard_delete_removes_documents_and_their_vectors(env):
    session, alice, _, store = env
    group = group_service.create_group(session, alice, "Old", BackgroundTasks())
    in_group = [_doc(session, alice, group.id).id, _doc(session, alice, group.id).id]
    outside = _doc(session, alice).id

    assert group_service.delete_group(session, alice, group.id, hard_delete=True, background_tasks=BackgroundTasks())
    session.commit()
    assert session.query(Document.id).all() == [(outside,)]
    assert store.deleted == [(alice, sorted(in_group))]


def test_soft_delete_keeps_documents_and_vectors(env):
    session, alice, _, store = env
    group = group_service.create_group(session, alice, "Old", BackgroundTasks())
    doc_id = _doc(session, alice, group.id).id
    assert group_service.delete_group(session, alice, group.id, background_tasks=BackgroundTasks())
    session.commit()
    assert session.get(Document, doc_id) is not None
    assert store.deleted == []


def test_move_document_only_between_own_documents_and_groups(env):
    session, alice, bob, _ = env
    alice_group = group_service.create_group(session, alice, "A", BackgroundTasks())
    bob_group = group_service.create_group(session, bob, "B", BackgroundTasks())
    alice_doc = _doc(session, alice)
    bob_doc = _doc(session, bob)

    assert group_service.move_document(session, alice, alice_doc.id, bob_group.id, BackgroundTasks()) is None
    assert group_service.move_document(session, alice, bob_doc.id, alice_group.id, BackgroundTasks()) is None
    moved = group_service.move_document(session, alice, alice_doc.id, alice_group.id, BackgroundTasks())
    assert moved.group_id == alice_group.id
    assert group_service.move_document(session, alice, alice_doc.id, None, BackgroundTasks()).group_id is None
