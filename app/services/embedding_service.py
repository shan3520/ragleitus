"""Which embedding model a user's documents are embedded with.

By default every user's documents are embedded by the server's own model
("local": fastembed, or the fake embedder in tests). A user can instead embed
through one of their provider keys (OpenAI, Gemini, Mistral, Together AI,
NVIDIA NIM or a self-hosted server). The choice applies to documents indexed
from then on; each document records the model its vectors were made with
(Document.embedding_provider/_model/_dimension), so a question is embedded
with the same model as the documents it searches, and documents made with
different models can be searched side by side.

Vectors of each model live in their own collection, named after the model
and the vector size (see VectorStore).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.user_settings import UserSettings
from app.services import telemetry
from app.services.embeddings import Embedder, get_embedder
from app.services.llm.base import ProviderError
from app.services.llm.embeddings import ProviderEmbedder
from app.services.llm.registry import PROVIDERS, UnknownProviderError, get_spec
from app.services.provider_key import decrypt_key, get_provider_key, list_provider_keys
from app.services.vector_store import VectorStore, get_vector_store, store_for

LOCAL = "local"


class EmbeddingUnavailable(Exception):
    """The user's embedding choice can't be used right now (no key stored, for example).

    The message is shown to the user.
    """


class EmbeddingSettingsError(ValueError):
    """An embedding choice that can't be saved; the message is shown to the user."""


@dataclass(frozen=True)
class EmbeddingChoice:
    provider: str  # LOCAL or a provider name
    model: str

    @property
    def is_local(self) -> bool:
        return self.provider == LOCAL


def local_choice() -> EmbeddingChoice:
    return EmbeddingChoice(LOCAL, get_embedder().model_name)


def get_choice(session: Session, user_id: int) -> EmbeddingChoice:
    row = session.get(UserSettings, user_id)
    if row is None or row.embedding_provider == LOCAL:
        return local_choice()
    return EmbeddingChoice(row.embedding_provider, row.embedding_model or "")


def document_choice(provider: str | None, model: str | None) -> EmbeddingChoice:
    """The choice a document was embedded with; NULL means the local model."""
    if provider in (None, LOCAL):
        return local_choice()
    return EmbeddingChoice(provider, model or "")


# A function that builds an embedder for (session, user_id, choice); tests
# inject fakes in place of build_embedder.
EmbedderFactory = Callable[[Session, int, EmbeddingChoice], Embedder]


def build_embedder(session: Session, user_id: int, choice: EmbeddingChoice) -> Embedder:
    """An embedder for the choice, using the user's own key for a provider."""
    if choice.is_local:
        return get_embedder()
    try:
        spec = get_spec(choice.provider)
    except UnknownProviderError:
        raise EmbeddingUnavailable(f"Unknown embedding provider {choice.provider!r}.") from None
    key = get_provider_key(session, user_id, choice.provider)
    if key is None:
        raise EmbeddingUnavailable(
            f"No API key stored for {spec.label}, which your embedding setting uses. "
            "Add the key, or switch embeddings back to the local model in Settings."
        )
    try:
        return ProviderEmbedder(choice.provider, decrypt_key(key.encrypted_key), choice.model, key.base_url)
    except ProviderError as exc:
        raise EmbeddingUnavailable(exc.message) from None


def store_for_choice(choice: EmbeddingChoice, dimension: int | None, local_store: VectorStore | None = None) -> VectorStore | None:
    """The collection holding vectors of this model, or None if there can be none yet.

    `local_store` overrides the local model's store (tests pass an in-memory one).
    """
    if choice.is_local:
        return local_store or get_vector_store()
    if not dimension:
        return None
    return store_for(collection_model_name(choice), dimension)


def collection_model_name(choice: EmbeddingChoice) -> str:
    """What a provider model's collection is named after.

    Collection names keep only lowercase letters and digits, so distinct model
    names could otherwise share one ("x/y" and "x_y", or "Model" and "model")
    and mix vectors of different models. A hash of the exact name keeps them
    apart, and long self-hosted model names are cut to stay within Qdrant's
    limit on collection names.
    """
    exact = f"{choice.provider}/{choice.model}"
    digest = hashlib.sha256(exact.encode()).hexdigest()[:10]
    return f"{choice.provider}/{choice.model[:80]}/{digest}"


def document_embedding(document: Document) -> dict | None:
    """The model a document's vectors were made with, or None before it was first indexed."""
    if document.embedding_provider is None and document.status != "ready":
        return None
    choice = document_choice(document.embedding_provider, document.embedding_model)
    return {"provider": choice.provider, "model": choice.model}


def document_store(document: Document, local_store: VectorStore | None = None) -> VectorStore | None:
    """The collection holding a document's vectors."""
    return store_for_choice(
        document_choice(document.embedding_provider, document.embedding_model),
        document.embedding_dimension,
        local_store,
    )


def vector_locations(
    session: Session, user_id: int, document_ids: list[int], local_store: VectorStore | None = None
) -> list[tuple[VectorStore, list[int]]]:
    """Which collections hold these documents' vectors. Look them up before
    deleting the document rows, then pass the result to delete_vectors."""
    if not document_ids:
        return []
    rows = (
        session.query(Document.embedding_provider, Document.embedding_model, Document.embedding_dimension, Document.id)
        .filter(Document.user_id == user_id, Document.id.in_(document_ids))
        .all()
    )
    by_store: dict[int, tuple[VectorStore, list[int]]] = {}
    for provider, model, dimension, document_id in rows:
        store = store_for_choice(document_choice(provider, model), dimension, local_store)
        if store is not None:
            by_store.setdefault(id(store), (store, []))[1].append(document_id)
    return list(by_store.values())


def delete_vectors(user_id: int, locations: list[tuple[VectorStore, list[int]]]) -> None:
    for store, document_ids in locations:
        store.delete_documents(user_id, document_ids)


def record_calls(session: Session, user_id: int, embedder: Embedder) -> None:
    """Store telemetry for the provider calls an embedder has made, then forget them."""
    calls = getattr(embedder, "calls", None)
    if not calls:
        return
    for call in calls:
        telemetry.record_llm_call(
            session,
            user_id=user_id,
            operation="embedding",
            provider=embedder.provider,
            model=embedder.model,
            latency_ms=call.latency_ms,
            usage=call.usage,
            prompt_text=call.text if call.usage.prompt_tokens is None else "",
            error=call.error,
        )
    calls.clear()


# ---------------------------------------------------------------- settings


def options(session: Session, user_id: int) -> list[dict]:
    """What a user can choose from: the local model, and each provider that
    offers embeddings, marked with whether the user has a key for it."""
    keys = {k.provider for k in list_provider_keys(session, user_id)}
    local = local_choice()
    result = [{"provider": LOCAL, "label": "Local model (on this server)", "default_model": local.model, "has_key": True}]
    for spec in PROVIDERS.values():
        if spec.supports_embeddings:
            result.append(
                {
                    "provider": spec.name,
                    "label": spec.label,
                    "default_model": spec.embedding_model,
                    "has_key": spec.name in keys,
                }
            )
    return result


def document_counts(session: Session, user_id: int) -> list[dict]:
    """How many of the user's documents are embedded with each model."""
    rows = (
        session.query(Document.embedding_provider, Document.embedding_model, Document.status, func.count())
        .filter(Document.user_id == user_id)
        .group_by(Document.embedding_provider, Document.embedding_model, Document.status)
        .all()
    )
    counts: dict[tuple[str, str], int] = {}
    for provider, model, status, count in rows:
        if status != "ready":
            continue
        choice = document_choice(provider, model)
        counts[(choice.provider, choice.model)] = counts.get((choice.provider, choice.model), 0) + count
    return [{"provider": p, "model": m, "documents": n} for (p, m), n in sorted(counts.items())]


def outdated_document_ids(session: Session, user_id: int) -> list[int]:
    """Ready or failed documents not embedded with the user's current choice."""
    choice = get_choice(session, user_id)
    rows = (
        session.query(Document.id, Document.embedding_provider, Document.embedding_model)
        .filter(Document.user_id == user_id, Document.status.in_(("ready", "failed")), Document.content.isnot(None))
        .order_by(Document.id)
        .all()
    )
    return [doc_id for doc_id, provider, model in rows if document_choice(provider, model) != choice]


def describe(session: Session, user_id: int) -> dict:
    choice = get_choice(session, user_id)
    key_missing = not choice.is_local and get_provider_key(session, user_id, choice.provider) is None
    return {
        "provider": choice.provider,
        "model": choice.model,
        "key_missing": key_missing,
        "options": options(session, user_id),
        "documents": document_counts(session, user_id),
        "outdated": len(outdated_document_ids(session, user_id)),
        "indexing": session.query(func.count(Document.id))
        .filter(Document.user_id == user_id, Document.status.in_(("pending", "indexing")))
        .scalar(),
    }


def save_choice(
    session: Session,
    user_id: int,
    provider: str,
    model: str | None,
    factory: EmbedderFactory | None = None,
) -> EmbeddingChoice:
    """Check the choice by embedding a short text with it, then save it.

    Documents are not re-indexed here; see outdated_document_ids.
    """
    if provider == LOCAL:
        choice = local_choice()
    else:
        try:
            spec = get_spec(provider)
        except UnknownProviderError:
            raise EmbeddingSettingsError(f"Unknown provider {provider!r}.") from None
        if not spec.supports_embeddings:
            raise EmbeddingSettingsError(f"{spec.label} does not offer embeddings.")
        model = (model or "").strip() or spec.embedding_model
        if not model:
            raise EmbeddingSettingsError("Enter the name of the embedding model your server provides.")
        choice = EmbeddingChoice(provider, model)
        embedder = None
        try:
            embedder = (factory or build_embedder)(session, user_id, choice)
            embedder.embed_query("RAGForge embedding check")
        except EmbeddingUnavailable as exc:
            raise EmbeddingSettingsError(str(exc)) from None
        except ProviderError as exc:
            raise EmbeddingSettingsError(f"Could not embed with {spec.label} {model}: {exc.message}") from None
        finally:
            if embedder is not None:
                record_calls(session, user_id, embedder)

    row = session.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        session.add(row)
    row.embedding_provider = choice.provider
    row.embedding_model = None if choice.is_local else choice.model
    session.flush()
    return choice
