from app.services.provider_validation import is_valid_provider_key_format, verify_provider_key


class MockHTTPClient:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.requests = []

    def post(self, request, json=None):
        self.requests.append((request, json))
        return self


def test_provider_key_format_rejects_invalid_values():
    assert not is_valid_provider_key_format("openai", "bad-key")
    assert not is_valid_provider_key_format("gemini", "AIza-short")


def test_provider_key_verification_uses_mock_http_client():
    client = MockHTTPClient(status_code=200)
    assert verify_provider_key("openai", "sk-12345678", client=client)
    assert client.requests


def test_provider_key_verification_rejects_mocked_failure():
    client = MockHTTPClient(status_code=401)
    assert not verify_provider_key("openai", "sk-12345678", client=client)
