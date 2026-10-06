import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.telemetry_event import TelemetryEvent
from app.services import reranking
from app.services.llm import ProviderError
from app.services.llm.embeddings import EmbeddingCall
from app.services.llm.base import Usage
from app.services.provider_key import encrypt_key, save_provider_key
from app.services.reranking import RerankChoice, RerankSettingsError
from tests.helpers import make_user


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class _Recording:
    provider, model, model_name = "together", "Salesforce/Llama-Rank-V1", "together/Salesforce/Llama-Rank-V1"

    def __init__(self, scores=None, fail=None):
        self.scores, self.fail, self.calls = scores, fail, []

    def rerank(self, query, passages):
        self.calls.append(EmbeddingCall(12.0, Usage(), "\n".join([query, *passages]), self.fail))
        if self.fail:
            raise self.fail
        return self.scores if self.scores is not None else [0.5] * len(passages)


def test_reranking_is_off_until_chosen(db_session):
    user = make_user(db_session)
    assert reranking.get_choice(db_session, user.id).is_off
    described = reranking.describe(db_session, user.id)
    assert described["provider"] == "none" and described["candidates"] == 20
    providers = [o["provider"] for o in described["options"]]
    assert providers == ["none", "local", "together", "custom"]  # NVIDIA only to users with its key
    save_provider_key(db_session, user.id, "nvidia", encrypt_key("nvapi-existingkey1234"))
    assert "nvidia" in [o["provider"] for o in reranking.options(db_session, user.id)]


def test_choose_local_then_a_provider_then_off(db_session):
    user = make_user(db_session)
    assert reranking.save_choice(db_session, user.id, "local", None).is_local
    assert reranking.get_choice(db_session, user.id) == reranking.local_choice()

    with pytest.raises(RerankSettingsError, match="No API key stored for Together AI"):
        reranking.save_choice(db_session, user.id, "together", None)
    save_provider_key(db_session, user.id, "together", encrypt_key("tgp-rerankkey1234"))
    fake = _Recording()
    choice = reranking.save_choice(db_session, user.id, "together", None, factory=lambda s, u, c: fake)
    assert choice == RerankChoice("together", "Salesforce/Llama-Rank-V1")  # the provider's default model
    assert reranking.get_choice(db_session, user.id) == choice
    # The check call is in telemetry, as a rerank.
    event = db_session.query(TelemetryEvent).one()
    assert (event.operation, event.provider, event.model, event.status) == ("rerank", "together", "Salesforce/Llama-Rank-V1", "ok")

    assert reranking.save_choice(db_session, user.id, "none", None).is_off
    assert reranking.get_choice(db_session, user.id).is_off


@pytest.mark.parametrize(
    "provider, model, message",
    [
        ("openai", None, "OpenAI does not offer reranking"),
        ("nonsense", None, "Unknown provider"),
        ("custom", "", "Enter the name of the reranking model"),
    ],
)
def test_invalid_choices_are_refused(db_session, provider, model, message):
    user = make_user(db_session)
    with pytest.raises(RerankSettingsError, match=message):
        reranking.save_choice(db_session, user.id, provider, model)
    assert reranking.get_choice(db_session, user.id).is_off


def test_a_reranker_that_fails_its_check_is_not_saved(db_session):
    user = make_user(db_session)
    save_provider_key(db_session, user.id, "together", encrypt_key("tgp-rerankkey1234"))
    for fake, message in [
        (_Recording(fail=ProviderError("Together AI returned HTTP 401: invalid key", 401)), "HTTP 401: invalid key"),
        (_Recording(scores=[0.1]), "did not score every passage"),
    ]:
        with pytest.raises(RerankSettingsError, match=message):
            reranking.save_choice(db_session, user.id, "together", None, factory=lambda s, u, c, fake=fake: fake)
    assert reranking.get_choice(db_session, user.id).is_off

    def broken(session_, user_id, choice):
        raise OSError("no space left on device")

    with pytest.raises(RerankSettingsError, match=r"Could not rerank with the local model \(OSError\)"):
        reranking.save_choice(db_session, user.id, "local", None, factory=broken)


def test_build_reranker_uses_the_stored_key(db_session):
    user = make_user(db_session)
    with pytest.raises(reranking.RerankUnavailable, match="No API key"):
        reranking.build_reranker(db_session, user.id, RerankChoice("nvidia", "nvidia/llama-3.2-nv-rerankqa-1b-v2"))
    save_provider_key(db_session, user.id, "nvidia", encrypt_key("nvapi-rerankkey1234"))
    built = reranking.build_reranker(db_session, user.id, RerankChoice("nvidia", "nvidia/llama-3.2-nv-rerankqa-1b-v2"))
    assert built.provider == "nvidia" and built._api_key == "nvapi-rerankkey1234"
    with pytest.raises(reranking.RerankUnavailable):
        reranking.build_reranker(db_session, user.id, RerankChoice("none", ""))
