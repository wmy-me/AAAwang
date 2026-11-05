"""Application settings loaded from environment variables and ``.env``."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class McpServiceConfig(BaseModel):
    """Trusted backend configuration for one MCP service."""

    url: str
    transport: Literal["streamable_http"] = "streamable_http"
    timeout_seconds: float = Field(default=10.0, gt=0)
    enabled: bool = True
    auth_token: SecretStr | None = None
    auth_query_parameter: str | None = None
    allowed_tool_names: tuple[str, ...] = ()


def default_mcp_services() -> dict[str, McpServiceConfig]:
    """Return local development services without opening any connections."""
    return {
        "shopping": McpServiceConfig(url="http://127.0.0.1:8101/mcp"),
    }


class Settings(BaseSettings):
    """Basic application settings with development-friendly defaults."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "life-buy-agent-api"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://life_buy:postgres@127.0.0.1:55432/"
        "life_buy_agent"
    )
    session_cookie_name: str = "life_agent_session"
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_cookie_max_age_seconds: int = Field(default=86400, gt=0)
    trusted_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-flash"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 60.0
    mcp_services: dict[str, McpServiceConfig] = Field(default_factory=default_mcp_services)
    map_mcp_url: str = "https://mcp.amap.com/mcp"
    map_mcp_key: SecretStr | None = None
    map_mcp_timeout_seconds: float = Field(default=20.0, gt=0)
    map_mcp_enabled: bool = False
    map_mcp_tool_name: str = "maps_text_search"
    map_mcp_weather_tool_name: str = "maps_weather"
    run_worker_lease_seconds: int = Field(default=30, gt=0)
    run_worker_poll_seconds: float = Field(default=1.0, gt=0)
    run_worker_max_attempts: int = Field(default=3, ge=1, le=20)
    shopping_agent_total_timeout_seconds: float = Field(default=180.0, gt=0, le=180.0)
    run_events_poll_seconds: float = Field(default=1.0, gt=0)
    run_events_heartbeat_seconds: float = Field(default=15.0, gt=0)
    run_events_batch_size: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def validate_cookie_security(self) -> "Settings":
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise ValueError("SameSite=None 要求 SESSION_COOKIE_SECURE=true。")
        if self.app_env.casefold() == "production" and not self.session_cookie_secure:
            raise ValueError("生产环境要求 SESSION_COOKIE_SECURE=true。")
        if self.map_mcp_enabled:
            if self.map_mcp_key is None or not self.map_mcp_key.get_secret_value().strip():
                raise ValueError("MAP_MCP_ENABLED=true 时必须配置 MAP_MCP_KEY。")
            if not self.map_mcp_tool_name.strip():
                raise ValueError("MAP_MCP_TOOL_NAME 不能为空。")
            if not self.map_mcp_weather_tool_name.strip():
                raise ValueError("MAP_MCP_WEATHER_TOOL_NAME 不能为空。")
            self.mcp_services["map"] = McpServiceConfig(
                url=self.map_mcp_url,
                timeout_seconds=self.map_mcp_timeout_seconds,
                enabled=True,
                auth_token=self.map_mcp_key,
                auth_query_parameter="key",
                allowed_tool_names=tuple(
                    dict.fromkeys(
                        (
                            self.map_mcp_tool_name.strip(),
                            self.map_mcp_weather_tool_name.strip(),
                        )
                    )
                ),
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
