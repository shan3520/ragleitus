import asyncio

from app.services.llm import ProviderError
from app.services.provider_validation import is_valid_provider_key_format, verify_provider_key
from tests.fakes import FakeFactory, FakeProvider


def test_provider_key_format_rejects_invalid_values():
    assert not is_valid_provider_key_format("openai", "bad-key")
    assert not is_valid_provider_key_format("gemini", "AIza-short")
    assert not is_valid_provider_key_format("anthropic", "sk-not-anthropic")
    assert not is_valid_provider_key_format("groq", "   ")
    assert not is_valid_provider_key_format("no-such-provider", "anything")


def test_provider_key_format_accepts_known_shapes():
    assert is_valid_provider_key_format("openai", "sk-proj-abc12345")
    assert is_valid_provider_key_format("anthropic", "sk-ant-api03-abcdefgh")
    # Gemini: standard keys, and the "auth keys" AI Studio has issued since May 2026.
    assert is_valid_provider_key_format("gemini", "AIzaSyFakeFakeFakeFakeFakeFakeFake00")
    assert is_valid_provider_key_format("gemini", "AQ.AbFakeFakeFakeFakeFake-Fake_Fake.Fake00")
    assert not is_valid_provider_key_format("gemini", "AQ.short")
    assert not is_valid_provider_key_format("gemini", "AQ.Fake Fake Fake Fake Fake Fake")
    # Providers without a published key format accept any non-empty key.
    assert is_valid_provider_key_format("groq", "gsk_anything")


def test_verification_lists_models_with_the_key():
    factory = FakeFactory(FakeProvider(models=["a", "b"]))
    check = asyncio.run(verify_provider_key("openai", "sk-12345678", factory=factory))
    assert check.valid
    assert "2 models" in check.detail
    assert factory.created == [("openai", "sk-12345678", None)]


def test_verification_skips_network_for_malformed_key():
    factory = FakeFactory()
    check = asyncio.run(verify_provider_key("openai", "not-a-key", factory=factory))
    assert not check.valid
    assert factory.created == []


def test_verification_reports_rejected_key():
    factory = FakeFactory(FakeProvider(error=ProviderError("HTTP 401", status_code=401)))
    check = asyncio.run(verify_provider_key("openai", "sk-12345678", factory=factory))
    assert not check.valid
    assert not check.unreachable
    assert check.detail == "OpenAI rejected the key."


def test_verification_distinguishes_unreachable_provider():
    factory = FakeFactory(FakeProvider(error=ProviderError("Could not reach groq (ConnectError)")))
    check = asyncio.run(verify_provider_key("groq", "gsk_key", factory=factory))
    assert not check.valid
    assert check.unreachable
