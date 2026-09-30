import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_require_jwt_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "jwt_secret" in str(exc.value)


def test_settings_require_provider_key_secret(monkeypatch):
    monkeypatch.delenv("PROVIDER_KEY_SECRET", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "provider_key_secret" in str(exc.value)


def test_settings_reject_short_secrets(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secrets_are_not_exposed_in_repr():
    settings = Settings(_env_file=None)
    assert settings.jwt_secret.get_secret_value() not in repr(settings)
    assert settings.provider_key_secret.get_secret_value() not in repr(settings)


def test_cors_origins_accepts_comma_separated_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
