import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.conversation import Conversation
from app.services import prompt_service
from app.services.prompt_service import PromptError, PromptNotFoundError
from tests.helpers import make_user

TEMPLATE = "Be brief. Passages:\n{context}"


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_create_version_and_clone(session):
    user = make_user(session)
    prompt = prompt_service.create_prompt(session, user.id, "  Concise  ", TEMPLATE, "Short answers", note="first")
    assert (prompt.name, prompt.description) == ("Concise", "Short answers")
    assert [(v.version, v.note) for v in prompt.versions] == [(1, "first")]

    v2 = prompt_service.add_version(session, user.id, prompt.id, "Even briefer.\n{context}\nQ: {question}", note="shorter")
    assert v2.version == 2
    session.expire_all()
    data = prompt_service.prompt_dict(prompt_service.get_prompt(session, user.id, prompt.id), with_versions=True)
    assert data["version_count"] == 2
    assert data["latest_version"]["version"] == 2
    assert [v["version"] for v in data["versions"]] == [2, 1]

    copy = prompt_service.clone_prompt(session, user.id, prompt.id)
    assert copy.name == "Concise (copy)"
    assert copy.versions[0].template == v2.template
    assert copy.versions[0].note == "Copied from Concise v2"
    assert [p.name for p in prompt_service.list_prompts(session, user.id)] == ["Concise", "Concise (copy)"]


@pytest.mark.parametrize(
    "template, message",
    [("", "empty"), ("   ", "empty"), ("No passages here.", "must contain {context}"), ("x{context}" * 3000, "longer than")],
)
def test_templates_must_place_the_passages(session, template, message):
    user = make_user(session)
    with pytest.raises(PromptError, match=message):
        prompt_service.create_prompt(session, user.id, "P", template)


def test_prompts_are_private(session):
    alice, bob = make_user(session), make_user(session)
    prompt = prompt_service.create_prompt(session, alice.id, "Mine", TEMPLATE)
    version_id = prompt.versions[0].id
    with pytest.raises(PromptNotFoundError):
        prompt_service.get_prompt(session, bob.id, prompt.id)
    with pytest.raises(PromptNotFoundError):
        prompt_service.get_version(session, bob.id, version_id)
    with pytest.raises(PromptNotFoundError):
        prompt_service.add_version(session, bob.id, prompt.id, TEMPLATE)
    with pytest.raises(PromptNotFoundError):
        prompt_service.clone_prompt(session, bob.id, prompt.id)
    assert prompt_service.list_prompts(session, bob.id) == []


def test_deleting_a_prompt_returns_conversations_to_the_built_in_prompt(session):
    user = make_user(session)
    prompt = prompt_service.create_prompt(session, user.id, "P", TEMPLATE)
    conversation = Conversation(user_id=user.id, title="c", prompt_version_id=prompt.versions[0].id)
    session.add(conversation)
    session.commit()

    prompt_service.delete_prompt(session, user.id, prompt.id)
    session.commit()
    session.refresh(conversation)
    assert conversation.prompt_version_id is None
    assert "{context}" in prompt_service.default_template()
