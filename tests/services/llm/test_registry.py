import pytest

from app.services.llm import PROVIDERS, UnknownProviderError, create_provider, get_spec
from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.openai_compatible import OpenAICompatibleProvider


def test_spec_lists_every_provider_in_the_spec():
    assert {"openai", "gemini", "anthropic", "groq", "openrouter", "nvidia", "together", "mistral"} <= set(PROVIDERS)


def test_create_provider_picks_adapter_by_kind():
    assert isinstance(create_provider("anthropic", "sk-ant-x"), AnthropicProvider)
    assert isinstance(create_provider("gemini", "AIza-x"), GeminiProvider)
    groq = create_provider("groq", "gsk")
    assert isinstance(groq, OpenAICompatibleProvider)
    assert groq._base_url == "https://api.groq.com/openai/v1"


def test_custom_provider_requires_base_url():
    with pytest.raises(ValueError):
        create_provider("custom", "key")
    provider = create_provider("custom", "key", "http://localhost:11434/v1/")
    assert provider._base_url == "http://localhost:11434/v1"


def test_unknown_provider():
    with pytest.raises(UnknownProviderError):
        get_spec("nope")
