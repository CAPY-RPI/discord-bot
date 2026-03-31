"""Schemas for onboarding setup and user state."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Literal

from pydantic import BaseModel


class GuildSetupConfig(BaseModel):
    """In-memory onboarding configuration for a guild."""

    enabled: bool = True
    log_channel_id: int | None = None
    welcome_channel_id: int | None = None
    welcome_dm_enabled: bool = False
    auto_kick_unverified: bool = False
    grace_period_hours: int = 24
    log_events: bool = True
    rules_location: str | None = None
    verification_acceptance: Literal["button_ack"] = "button_ack"
    member_role_id: int | None = None
    onboarding_message_template: str | None = None


class UserOnboardingState(BaseModel):
    """In-memory onboarding lifecycle state for a user in a guild."""

    status: Literal["new", "pending", "verified"] = "new"
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None
    attempts: int = 0
