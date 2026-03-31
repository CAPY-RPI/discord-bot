"""Business logic and data access for guild settings."""

from __future__ import annotations

import logging

from ._schemas import GuildSettings

log = logging.getLogger(__name__)


class GuildService:
    """Handles guild settings persistence and business logic."""

    def __init__(self, store: dict[int, GuildSettings]) -> None:
        self._store = store

    def get_settings(self, guild_id: int) -> GuildSettings:
        """Return existing settings for a guild or create defaults."""
        if guild_id not in self._store:
            self._store[guild_id] = GuildSettings()
        return self._store[guild_id]

    def update_channels(
        self,
        guild_id: int,
        *,
        reports: str,
        announcements: str,
        feedback: str,
    ) -> GuildSettings:
        """Persist channel IDs for a guild."""
        settings = self.get_settings(guild_id)
        settings.reports_channel = int(reports) if reports.isdigit() else None
        settings.announcements_channel = int(announcements) if announcements.isdigit() else None
        settings.feedback_channel = int(feedback) if feedback.isdigit() else None
        log.debug("Updated channels for guild %d", guild_id)
        return settings

    def update_roles(
        self,
        guild_id: int,
        *,
        admin: str,
        member: str,
    ) -> GuildSettings:
        """Persist role IDs for a guild."""
        settings = self.get_settings(guild_id)
        settings.admin_role = admin or None
        settings.member_role = member or None
        log.debug("Updated roles for guild %d", guild_id)
        return settings

    def update_announcement_channel(self, guild_id: int, *, channel: str) -> GuildSettings:
        """Persist the announcement channel for a guild."""
        settings = self.get_settings(guild_id)
        settings.announcements_channel = int(channel) if channel.isdigit() else None
        log.debug("Updated announcement channel for guild %d", guild_id)
        return settings

    def update_feedback_channel(self, guild_id: int, *, channel: str) -> GuildSettings:
        """Persist the feedback channel for a guild."""
        settings = self.get_settings(guild_id)
        settings.feedback_channel = int(channel) if channel.isdigit() else None
        log.debug("Updated feedback channel for guild %d", guild_id)
        return settings

    def update_welcome_message(self, guild_id: int, *, message: str) -> GuildSettings:
        """Persist the onboarding welcome message for a guild."""
        settings = self.get_settings(guild_id)
        settings.onboarding_welcome = message or None
        log.debug("Updated welcome message for guild %d", guild_id)
        return settings
