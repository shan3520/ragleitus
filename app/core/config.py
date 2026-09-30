"""Application settings, read from environment variables and `.env`.

`JWT_SECRET` and `PROVIDER_KEY_SECRET` have no defaults: the application
refuses to start without them rather than signing tokens or encrypting
provider keys with a guessable value.
"""

from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ragforge"
    VERSION: str = "0.1.0"
    debug: bool = False

    # Persistence
    database_url: str = "sqlite:///./ragforge.db"

    # Security
    # HS256 needs at least 32 bytes of key (RFC 7518 §3.2).
    jwt_secret: SecretStr = Field(min_length=32)
    provider_key_secret: SecretStr = Field(min_length=16)
    access_token_ttl_minutes: int = 60 * 24
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # Vector store: an http(s) URL for a Qdrant server, ":memory:" for an
    # in-process store, or a filesystem path for Qdrant's embedded local mode.
    vector_store_url: str = "./data/qdrant"
    vector_store_api_key: SecretStr = SecretStr("")

    # Embeddings: "fastembed" runs a small local ONNX model, "fake" is a
    # deterministic hashing embedder for tests and offline development.
    embedding_backend: Literal["fastembed", "fake"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str | None = None

    # Ingestion and retrieval
    chunk_window_size: int = 800
    chunk_overlap_size: int = 100
    max_upload_mb: int = 25
    retrieval_top_k: int = 6
    chat_history_turns: int = 6
    llm_max_output_tokens: int = 16000

    # HTTP
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 20
    llm_timeout_seconds: float = 120.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
