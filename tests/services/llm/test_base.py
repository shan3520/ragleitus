import asyncio

from app.services.llm.base import ChatMessage, ProviderError, Usage, complete, split_system
from tests.fakes import FakeProvider


def test_complete_joins_deltas_and_keeps_usage_and_model():
    provider = FakeProvider(reply="one two three", usage=Usage(12, 3), served_model="served-1")
    result = asyncio.run(complete(provider, [ChatMessage("user", "hi")], "requested", 50))
    assert result.text == "one two three"
    assert result.usage == Usage(12, 3)
    assert (result.model, result.finish_reason) == ("served-1", "stop")
    assert provider.calls[0]["max_tokens"] == 50


def test_split_system_joins_system_messages():
    system, turns = split_system(
        [ChatMessage("system", "A"), ChatMessage("user", "q"), ChatMessage("system", "B"), ChatMessage("assistant", "a")]
    )
    assert system == "A\n\nB"
    assert [m.role for m in turns] == ["user", "assistant"]


def test_only_401_and_403_are_auth_errors():
    assert ProviderError("x", 401).is_auth_error
    assert ProviderError("x", 403).is_auth_error
    assert not ProviderError("x", 429).is_auth_error
    assert not ProviderError("x").is_auth_error
