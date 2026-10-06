"""Which reranker, if any, a user's retrieval results are reranked with.

Off by default. A user can turn on the server's own cross-encoder ("local",
see rerankers) or a provider's rerank API through one of their keys
(Together AI, NVIDIA NIM or a self-hosted server; see llm.rerank). When it is
on, retrieval hands the best RERANK_CANDIDATES fused passages to the
reranker and keeps the top_k it scores highest (see retrieval.retrieve).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user_settings import UserSettings
from app.services import telemetry
from app.services.llm.base import ProviderError
from app.services.llm.registry import PROVIDERS, UnknownProviderError, get_spec
from app.services.llm.rerank import ProviderReranker
from app.services.provider_key import decrypt_key, get_provider_key, list_provider_keys
from app.services.rerankers import Reranker, get_local_reranker

logger = logging.getLogger(__name__)

OFF = "none"
LOCAL = "local"


class RerankUnavailable(Exception):
    """The user's reranker can't be used right now (no key stored, for example).

    The message is shown to the user.
    """


class RerankSettingsError(ValueError):
    """A reranking choice that can't be saved; the message is shown to the user."""


@dataclass(frozen=True)
class RerankChoice:
    provider: str  # OFF, LOCAL or a provider name
    model: str

    @property
    def is_off(self) -> bool:
        return self.provider == OFF

    @property
    def is_local(self) -> bool:
        return self.provider == LOCAL


def local_choice() -> RerankChoice:
    return RerankChoice(LOCAL, settings.local_rerank_model)


def get_choice(session: Session, user_id: int) -> RerankChoice:
    row = session.get(UserSettings, user_id)
    provider = row.rerank_provider if row is not None else OFF
    if provider in (None, OFF):
        return RerankChoice(OFF, "")
    if provider == LOCAL:
        return local_choice()
    return RerankChoice(provider, row.rerank_model or "")


# A function that builds a reranker for (session, user_id, choice); tests
# inject fakes in place of build_reranker.
RerankerFactory = Callable[[Session, int, RerankChoice], Reranker]


def build_reranker(session: Session, user_id: int, choice: RerankChoice) -> Reranker:
    """A reranker for the choice, using the user's own key for a provider."""
    if choice.is_off:
        raise RerankUnavailable("Reranking is off.")
    if choice.is_local:
        return get_local_reranker()
    try:
        spec = get_spec(choice.provider)
    except UnknownProviderError:
        raise RerankUnavailable(f"Unknown reranking provider {choice.provider!r}.") from None
    key = get_provider_key(session, user_id, choice.provider)
    if key is None:
        raise RerankUnavailable(
            f"No API key stored for {spec.label}, which your reranking setting uses. "
            "Add the key, or change reranking in Settings."
        )
    try:
        return ProviderReranker(choice.provider, decrypt_key(key.encrypted_key), choice.model, key.base_url)
    except ProviderError as exc:
        raise RerankUnavailable(exc.message) from None


def record_calls(session: Session, user_id: int, reranker: Reranker) -> None:
    """Store telemetry for the provider calls a reranker has made, then forget them."""
    calls = getattr(reranker, "calls", None)
    if not calls:
        return
    for call in calls:
        telemetry.record_llm_call(
            session,
            user_id=user_id,
            operation="rerank",
            provider=reranker.provider,
            model=reranker.model,
            latency_ms=call.latency_ms,
            usage=call.usage,
            prompt_text=call.text,
            error=call.error,
        )
    calls.clear()


def rerank(reranker: Reranker, query: str, passages: list[str]) -> list[float]:
    """The reranker's scores, checked: one number per passage."""
    scores = reranker.rerank(query, passages)
    if len(scores) != len(passages):
        raise ProviderError("The reranker did not score every passage.")
    return [float(s) for s in scores]


# ---------------------------------------------------------------- settings


def options(session: Session, user_id: int) -> list[dict]:
    """Off, the local model, and each provider that offers reranking (with whether the user has its key)."""
    keys = {k.provider for k in list_provider_keys(session, user_id)}
    current = get_choice(session, user_id).provider
    result = [
        {"provider": OFF, "label": "Off", "default_model": "", "has_key": True},
        {"provider": LOCAL, "label": "Local model (on this server)", "default_model": settings.local_rerank_model, "has_key": True},
    ]
    for spec in PROVIDERS.values():
        # Not offered for new keys: listed only to users who have one or chose it.
        if spec.supports_reranking and (spec.offered or spec.name in keys or spec.name == current):
            result.append(
                {"provider": spec.name, "label": spec.label, "default_model": spec.rerank_model, "has_key": spec.name in keys}
            )
    return result


def describe(session: Session, user_id: int) -> dict:
    choice = get_choice(session, user_id)
    key_missing = not (choice.is_off or choice.is_local) and get_provider_key(session, user_id, choice.provider) is None
    return {
        "provider": choice.provider,
        "model": choice.model,
        "key_missing": key_missing,
        "candidates": settings.rerank_candidates,
        "options": options(session, user_id),
    }


def save_choice(
    session: Session,
    user_id: int,
    provider: str,
    model: str | None,
    factory: RerankerFactory | None = None,
) -> RerankChoice:
    """Check the choice by reranking a short text with it, then save it."""
    if provider == OFF:
        choice = RerankChoice(OFF, "")
    else:
        if provider == LOCAL:
            choice, label = local_choice(), "the local model"
        else:
            try:
                spec = get_spec(provider)
            except UnknownProviderError:
                raise RerankSettingsError(f"Unknown provider {provider!r}.") from None
            if not spec.supports_reranking:
                raise RerankSettingsError(f"{spec.label} does not offer reranking.")
            model = (model or "").strip() or spec.rerank_model
            if not model:
                raise RerankSettingsError("Enter the name of the reranking model your server provides.")
            choice, label = RerankChoice(provider, model), f"{spec.label} {model}"
        reranker = None
        try:
            reranker = (factory or build_reranker)(session, user_id, choice)
            rerank(reranker, "RAGForge reranking check", ["A passage to score.", "Another passage."])
        except RerankUnavailable as exc:
            raise RerankSettingsError(str(exc)) from None
        except ProviderError as exc:
            raise RerankSettingsError(f"Could not rerank with {label}: {exc.message}") from None
        except Exception as exc:  # the local model failed to load (no download, no disk space)
            logger.exception("Reranker check failed", extra={"provider": choice.provider})
            raise RerankSettingsError(f"Could not rerank with {label} ({type(exc).__name__}).") from None
        finally:
            if reranker is not None:
                record_calls(session, user_id, reranker)

    row = session.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        session.add(row)
    row.rerank_provider = choice.provider
    row.rerank_model = choice.model if not (choice.is_off or choice.is_local) else None
    session.flush()
    return choice
