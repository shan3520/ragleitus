import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.document import Document
from app.models.telemetry_event import TelemetryEvent
from app.services import embedding_service
from app.services.embedding_service import LOCAL, EmbeddingChoice, EmbeddingSettingsError
from app.services.llm import ProviderError
from app.services.provider_key import encrypt_key, save_provider_key
from tests.fakes import FakeProviderEmbedder, provider_embedder_factory
from tests.helpers import make_user


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def user(session):
    user = make_user(session)
    session.commit()
    return user


def _key(session, user, provider="openai", base_url=None):
    save_provider_key(session, user.id, provider, encrypt_key("sk-test-key-123456"), base_url)
    session.commit()


def test_everyone_starts_on_the_local_model(session, user):
    choice = embedding_service.get_choice(session, user.id)
    assert choice.is_local and choice.model == "fake-hash"
    described = embedding_service.describe(session, user.id)
    assert described["provider"] == LOCAL and described["key_missing"] is False
    providers = {o["provider"]: o for o in described["options"]}
    # Only providers that offer embeddings are offered (NVIDIA only to users with its key).
    assert {"local", "openai", "gemini", "mistral", "together", "custom"} == set(providers)
    assert providers["openai"]["default_model"] == "text-embedding-3-small"
    assert providers["openai"]["has_key"] is False


def test_saving_a_provider_checks_it_with_one_embedding_and_records_the_call(session, user):
    factory = provider_embedder_factory()
    choice = embedding_service.save_choice(session, user.id, "openai", None, factory=factory)
    session.commit()

    assert choice == EmbeddingChoice("openai", "text-embedding-3-small")
    assert embedding_service.get_choice(session, user.id) == choice
    assert len(factory.built) == 1 and len(factory.built[0].calls) == 0  # recorded, then forgotten
    event = session.query(TelemetryEvent).one()
    assert (event.operation, event.provider, event.model, event.prompt_tokens) == ("embedding", "openai", "text-embedding-3-small", 3)

    embedding_service.save_choice(session, user.id, "local", None)
    assert embedding_service.get_choice(session, user.id).is_local


@pytest.mark.parametrize(
    "provider, model, message",
    [
        ("nonsense", None, "Unknown provider"),
        ("anthropic", None, "does not offer embeddings"),
        ("custom", "  ", "Enter the name of the embedding model"),
    ],
)
def test_choices_that_cannot_work_are_refused(session, user, provider, model, message):
    with pytest.raises(EmbeddingSettingsError, match=message):
        embedding_service.save_choice(session, user.id, provider, model, factory=provider_embedder_factory())
    assert embedding_service.get_choice(session, user.id).is_local


def test_a_provider_without_a_key_or_failing_the_check_is_refused(session, user):
    # The real factory: no key stored.
    with pytest.raises(EmbeddingSettingsError, match="No API key stored for OpenAI"):
        embedding_service.save_choice(session, user.id, "openai", None)

    failing = provider_embedder_factory(fail=ProviderError("OpenAI returned HTTP 404: model not found", 404))
    with pytest.raises(EmbeddingSettingsError, match="Could not embed with OpenAI text-embedding-9: OpenAI returned HTTP 404"):
        embedding_service.save_choice(session, user.id, "openai", "text-embedding-9", factory=failing)
    assert embedding_service.get_choice(session, user.id).is_local
    # The failed check is still in telemetry.
    assert session.query(TelemetryEvent).one().status == "error"


def test_build_embedder_uses_the_users_key_and_base_url(session, user):
    _key(session, user, "custom", "https://llm.example.com/v1")
    embedder = embedding_service.build_embedder(session, user.id, EmbeddingChoice("custom", "nomic-embed-text"))
    assert embedder.model_name == "custom/nomic-embed-text"
    assert embedder._base_url == "https://llm.example.com/v1"
    assert embedder._api_key == "sk-test-key-123456"

    other = make_user(session)
    with pytest.raises(embedding_service.EmbeddingUnavailable, match="No API key stored"):
        embedding_service.build_embedder(session, other.id, EmbeddingChoice("custom", "nomic-embed-text"))

    _key(session, user, "openai")
    described = embedding_service.describe(session, user.id)
    assert {o["provider"]: o["has_key"] for o in described["options"]}["openai"] is True


def test_outdated_documents_and_counts_per_model(session, user):
    def doc(status, provider=None, model=None, content="text"):
        d = Document(user_id=user.id, title="d", status=status, content=content,
                     embedding_provider=provider, embedding_model=model, embedding_dimension=64 if provider else None)
        session.add(d)
        session.flush()
        return d.id

    legacy = doc("ready")
    local = doc("ready", LOCAL, "fake-hash")
    remote = doc("ready", "openai", "text-embedding-3-small")
    failed = doc("failed", "openai", "text-embedding-3-small")
    doc("indexing")
    doc("ready", content=None)  # nothing to re-index
    session.commit()

    assert embedding_service.outdated_document_ids(session, user.id) == [remote, failed]
    assert embedding_service.document_counts(session, user.id) == [
        {"provider": "local", "model": "fake-hash", "documents": 3},
        {"provider": "openai", "model": "text-embedding-3-small", "documents": 1},
    ]

    embedding_service.save_choice(session, user.id, "openai", None, factory=provider_embedder_factory())
    assert embedding_service.outdated_document_ids(session, user.id) == [legacy, local]
    assert embedding_service.describe(session, user.id)["outdated"] == 2


def test_vectors_are_found_in_each_documents_own_collection(session, user, vector_stores):
    local_store = object()
    a = Document(user_id=user.id, title="a", status="ready")
    b = Document(user_id=user.id, title="b", status="ready", embedding_provider="openai", embedding_model="m", embedding_dimension=8)
    c = Document(user_id=user.id, title="c", status="ready", embedding_provider="openai", embedding_model="m", embedding_dimension=8)
    d = Document(user_id=user.id, title="d", status="pending", embedding_provider="openai", embedding_model="m")  # no vectors yet
    session.add_all([a, b, c, d])
    session.flush()

    locations = embedding_service.vector_locations(session, user.id, [a.id, b.id, c.id, d.id], local_store=local_store)

    assert len(locations) == 2
    by_name = {getattr(store, "collection", "local"): ids for store, ids in locations}
    assert by_name["local"] == [a.id]
    remote = embedding_service.store_for_choice(EmbeddingChoice("openai", "m"), 8)
    assert by_name[remote.collection] == [b.id, c.id]
    other = make_user(session)
    assert embedding_service.vector_locations(session, other.id, [a.id], local_store=local_store) == []


def test_model_names_that_look_alike_get_separate_collections(vector_stores):
    def collection(provider, model, dimension=8):
        return embedding_service.store_for_choice(EmbeddingChoice(provider, model), dimension).collection

    names = {collection("custom", m) for m in ("x/y", "x_y", "X-Y", "x y")}
    assert len(names) == 4
    assert collection("openai", "text-embedding-3-small").startswith("chunks_openai_text_embedding_3_small_")
    assert collection("openai", "m", 8) != collection("openai", "m", 16)
    assert len(collection("custom", "m" * 255)) < 255
    assert embedding_service.store_for_choice(EmbeddingChoice(LOCAL, "fake-hash"), None, local_store="local") == "local"


def test_record_calls_ignores_embedders_without_a_log(session, user):
    embedding_service.record_calls(session, user.id, object())
    embedder = FakeProviderEmbedder()
    embedder.embed_query("hello there")
    embedding_service.record_calls(session, user.id, embedder)
    assert session.query(TelemetryEvent).count() == 1
    embedding_service.record_calls(session, user.id, embedder)
    assert session.query(TelemetryEvent).count() == 1


def test_a_provider_not_offered_for_new_keys_is_listed_only_to_users_who_have_its_key(session, user):
    assert "nvidia" not in {o["provider"] for o in embedding_service.options(session, user.id)}
    save_provider_key(session, user.id, "nvidia", encrypt_key("nvapi-existingkey1234"))
    option = {o["provider"]: o for o in embedding_service.options(session, user.id)}["nvidia"]
    assert option["has_key"] is True
