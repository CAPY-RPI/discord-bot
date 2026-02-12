import logging
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    """Environment configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


class Settings(EnvConfig):
    """Manages application settings using Pydantic."""

    log_level: int = logging.INFO
    prefix: str = "/"
    token: str = ""
    debug_guild_id: int | None = None

    # Ticket System Configuration
    ticket_feedback_channel_id: int = 0

    backend_environment: Literal["dev", "prod"] = "dev"
    backend_api_dev_base_url: str = "http://localhost:8080"
    backend_api_prod_base_url: str = ""
    backend_api_bot_token: str = ""
    backend_api_auth_cookie: str = ""
    backend_api_timeout_seconds: float = 10.0
    backend_api_max_connections: int = 20
    backend_api_max_keepalive_connections: int = 10

    @property
    def backend_api_base_url(self) -> str:
        """Resolve backend API base URL from selected environment."""
        if self.backend_environment == "dev":
            if self.backend_api_dev_base_url:
                return self.backend_api_dev_base_url

            msg = "backend_api_dev_base_url must be set when backend_environment is 'dev'"
            raise ValueError(msg)

        if self.backend_api_prod_base_url:
            return self.backend_api_prod_base_url

        msg = "backend_api_prod_base_url must be set when backend_environment is 'prod'"
        raise ValueError(msg)


settings = Settings()
