from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GuildChannels:
    """Channel destinations used by the bot for various purposes."""

    reports: int | None = None
    announcements: int | None = None
    moderator: int | None = None
    feedback: int | None = None


@dataclass
class GuildRoles:
    """Role identifiers used to gate features and permissions."""

    visitor: str | None = None
    member: str | None = None
    eboard: str | None = None
    admin: str | None = None
    advisor: str | None = None
    office_hours: str | None = None


@dataclass
class GuildSettings:
    """Top-level guild configuration model."""

    channels: GuildChannels = field(default_factory=GuildChannels)
    roles: GuildRoles = field(default_factory=GuildRoles)
    onboarding_welcome: str | None = None
