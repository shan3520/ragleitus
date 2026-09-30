import asyncio

import httpx
import pytest

from app.core.config import settings
from app.services.llm import ChatMessage, ProviderError, complete
from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.llm.url_guard import PRIVATE_URL_MESSAGE, ensure_public_url, is_public_address
from app.services.provider_validation import verify_provider_key


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "172.17.0.2", "192.168.1.10", "169.254.169.254", "100.64.0.1", "0.0.0.0",
     "::1", "fe80::1%eth0", "fd00::1", "::ffff:127.0.0.1"],
)
def test_private_and_special_addresses_are_not_public(address):
    assert not is_public_address(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:4700:4700::1111"])
def test_internet_addresses_are_public(address):
    assert is_public_address(address)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:6333", "http://localhost:11434/v1", "http://169.254.169.254/latest", "http://[::1]:8000"]
)
def test_private_urls_are_refused(url):
    with pytest.raises(ProviderError) as exc:
        asyncio.run(ensure_public_url(url))
    assert exc.value.status_code == 400
    assert exc.value.message == PRIVATE_URL_MESSAGE


def test_public_ip_literal_is_allowed():
    asyncio.run(ensure_public_url("https://93.184.216.34/v1"))


def test_operator_can_allow_private_urls(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_provider_urls", True)
    asyncio.run(ensure_public_url("http://localhost:11434/v1"))


def test_guarded_provider_refuses_before_connecting():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    provider = OpenAICompatibleProvider(
        "custom", "", "http://127.0.0.1:6333", transport=httpx.MockTransport(handler), url_guard=ensure_public_url
    )
    with pytest.raises(ProviderError):
        asyncio.run(provider.list_models())
    with pytest.raises(ProviderError):
        asyncio.run(complete(provider, [ChatMessage("user", "Hi")], "m", 10))
    assert calls == []


def test_error_body_can_be_withheld():
    def handler(request):
        return httpx.Response(404, json={"secret": "internal response body"})

    provider = OpenAICompatibleProvider(
        "custom", "", "https://93.184.216.34/v1", transport=httpx.MockTransport(handler), expose_error_body=False
    )
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.list_models())
    assert exc.value.message == "custom returned HTTP 404"


def test_key_check_for_private_custom_url_is_a_client_error():
    check = asyncio.run(verify_provider_key("custom", "none", "http://127.0.0.1:6333"))
    assert not check.valid
    assert not check.unreachable
    assert check.detail == PRIVATE_URL_MESSAGE
