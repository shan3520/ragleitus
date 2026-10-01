import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.services import saved_search_service
from tests.helpers import make_user


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def test_upsert_creates_then_updates_by_name(session):
    user = make_user(session)
    first = saved_search_service.upsert_saved_search(session, user.id, "triage", "errors", None)
    second = saved_search_service.upsert_saved_search(session, user.id, "triage", "warnings", {"level": "warn"})
    assert first.id == second.id
    assert (second.query_text, second.applied_filters) == ("warnings", {"level": "warn"})
    assert len(saved_search_service.list_saved_searches(session, user.id)) == 1


def test_searches_are_scoped_to_their_owner(session):
    alice, bob = make_user(session), make_user(session)
    mine = saved_search_service.upsert_saved_search(session, alice.id, "mine", "q", None)
    # Names are unique per user, not globally.
    theirs = saved_search_service.upsert_saved_search(session, bob.id, "mine", "q", None)
    assert mine.id != theirs.id

    assert saved_search_service.get_saved_search(session, bob.id, mine.id) is None
    assert saved_search_service.delete_saved_search(session, bob.id, mine.id) is False
    assert saved_search_service.get_saved_search(session, alice.id, mine.id) is not None

    assert saved_search_service.delete_saved_search(session, alice.id, mine.id) is True
    assert saved_search_service.list_saved_searches(session, alice.id) == []
    assert [s.id for s in saved_search_service.list_saved_searches(session, bob.id)] == [theirs.id]
