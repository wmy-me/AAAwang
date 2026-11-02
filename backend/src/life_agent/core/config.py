"""Application settings loaded from environment variables and ``.env``."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Basic application settings with development-friendly defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "life-buy-agent-api"
    app_env: str = "development"
    log_level: str = "INFO"
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-flash"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
