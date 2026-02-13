import logging

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

    # Event System Configuration
    announcement_channel_name: str = "test-announcements"


settings = Settings()
