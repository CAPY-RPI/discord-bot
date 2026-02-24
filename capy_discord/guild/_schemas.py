"""Pydantic models for guild settings used by ModelModal."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChannelSettingsForm(BaseModel):
    """Form for configuring guild channel destinations."""

    reports: str = Field(default="", title="Reports Channel", description="Channel ID for bug reports")
    announcements: str = Field(default="", title="Announcements Channel", description="Channel ID for announcements")
    feedback: str = Field(default="", title="Feedback Channel", description="Channel ID for feedback routing")


class RoleSettingsForm(BaseModel):
    """Form for configuring guild role scopes."""

    admin: str = Field(default="", title="Admin Role", description="Role ID for administrator access")
    member: str = Field(default="", title="Member Role", description="Role ID for general member access")


class AnnouncementChannelForm(BaseModel):
    """Form for setting the announcement channel."""

    channel: str = Field(default="", title="Announcement Channel", description="Channel ID for global pings")


class FeedbackChannelForm(BaseModel):
    """Form for setting the feedback channel."""

    channel: str = Field(default="", title="Feedback Channel", description="Channel ID for feedback routing")


class WelcomeMessageForm(BaseModel):
    """Form for customizing the onboarding welcome message."""

    message: str = Field(default="", title="Welcome Message", description="Custom welcome message for your guild")


class GuildSettings(BaseModel):
    """Persisted guild settings (not a form — internal state)."""

    reports_channel: int | None = None
    announcements_channel: int | None = None
    feedback_channel: int | None = None
    admin_role: str | None = None
    member_roles: list[str] = Field(default_factory=list)  # Store multiple member role IDs as strings
    onboarding_welcome: str | None = None
