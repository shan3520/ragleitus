from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "FastAPI App"
    PROJECT_NAME: str = "ragforge"
    VERSION: str = "0.1.0"
    debug: bool = False
    chunk_window_size: int = 800
    chunk_overlap_size: int = 100
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
