"""Application settings loaded from environment variables and ``.env``."""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpServiceConfig(BaseModel):
    """Trusted backend configuration for one MCP service."""

    url: str
    transport: Literal["streamable_http"] = "streamable_http"
    timeout_seconds: float = Field(default=10.0, gt=0)
    enabled: bool = True
    auth_token: SecretStr | None = None


def default_mcp_services() -> dict[str, McpServiceConfig]:
    """Return local development services without opening any connections."""
    return {
        "shopping": McpServiceConfig(url="http://127.0.0.1:8101/mcp"),
    }


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
    mcp_services: dict[str, McpServiceConfig] = Field(default_factory=default_mcp_services)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
