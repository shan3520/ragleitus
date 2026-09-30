"""Checks that a user's provider key works before it is stored.

A key first has to match the provider's known format (when there is one),
then the provider's list-models endpoint must accept it. Listing models costs
nothing and needs only the same credential a chat request would use.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.llm import ProviderError, ProviderFactory, UnknownProviderError, create_provider, get_spec


@dataclass(frozen=True)
class KeyCheck:
    valid: bool
    detail: str
    # True when the provider could not be reached, as opposed to rejecting the key.
    unreachable: bool = False


def is_valid_provider_key_format(provider: str, key: str) -> bool:
    try:
        spec = get_spec(provider.lower())
    except UnknownProviderError:
        return False
    if not key or not key.strip():
        return False
    return bool(spec.key_pattern.match(key)) if spec.key_pattern else True


async def verify_provider_key(
    provider: str,
    key: str,
    base_url: str | None = None,
    factory: ProviderFactory = create_provider,
) -> KeyCheck:
    spec = get_spec(provider)
    if not is_valid_provider_key_format(provider, key):
        return KeyCheck(False, f"That does not look like a {spec.label} API key.")
    try:
        models = await factory(provider, key, base_url).list_models()
    except ProviderError as exc:
        if exc.is_auth_error:
            return KeyCheck(False, f"{spec.label} rejected the key.")
        return KeyCheck(False, exc.message, unreachable=exc.status_code is None or exc.status_code >= 500)
    return KeyCheck(True, f"{spec.label} accepted the key ({len(models)} models available).")
