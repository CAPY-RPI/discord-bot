import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import discord
from pydantic import ValidationError

from ._schemas import UserProfileDetailsSchema, UserProfileIdentitySchema, UserProfileSchema


class ProfileExistsError(Exception):
    """Raised when a profile already exists for a create request."""


class ProfileNotFoundError(Exception):
    """Raised when a profile is required but does not exist."""


class InvalidProfileError(Exception):
    """Raised when combined profile data fails validation."""


class ProfileService:
    """Owns profile storage, validation, and presentation helpers."""

    def __init__(self, bot: discord.Client, log: logging.Logger) -> None:
        """Initialize the profile service and shared in-memory store."""
        self.log = log
        store: dict[int, UserProfileSchema] | None = getattr(bot, "profile_store", None)
        if store is None:
            store = {}
            setattr(bot, "profile_store", store)  # noqa: B010
        self._profiles = store

    def start_edit(self, user_id: int, action: str) -> dict[str, Any] | None:
        """Return existing profile data for an edit flow after validating the action."""
        profile = self._profiles.get(user_id)

        if action == "create" and profile:
            raise ProfileExistsError
        if action == "update" and not profile:
            raise ProfileNotFoundError

        return profile.model_dump() if profile else None

    def merge_identity_step(self, user_id: int, identity: UserProfileIdentitySchema) -> dict[str, Any]:
        """Combine the first modal step with any existing profile fields."""
        current_profile = self._profiles.get(user_id)
        profile_data = current_profile.model_dump() if current_profile else {}
        profile_data.update(identity.model_dump())
        return profile_data

    def build_profile(
        self,
        user: discord.abc.User,
        details: UserProfileDetailsSchema,
        profile_data: dict[str, Any],
    ) -> UserProfileSchema:
        """Combine modal steps into a validated profile model."""
        combined_data = {**profile_data, **details.model_dump()}

        try:
            return UserProfileSchema(**combined_data)
        except ValidationError as error:
            self.log.warning("Full profile validation failed for user %s: %s", user, error)
            raise InvalidProfileError from error

    def get_profile(self, user_id: int) -> UserProfileSchema:
        """Fetch a saved profile or raise when missing."""
        profile = self._profiles.get(user_id)
        if not profile:
            raise ProfileNotFoundError
        return profile

    def save_profile(self, user: discord.abc.User, profile: UserProfileSchema) -> None:
        """Persist a validated profile."""
        self._profiles[user.id] = profile
        self.log.info("Updated profile for user %s", user)

    def delete_profile(self, user: discord.abc.User) -> None:
        """Delete an existing profile."""
        self.get_profile(user.id)
        del self._profiles[user.id]
        self.log.info("Deleted profile for user %s", user)

    def create_profile_embed(self, user: discord.User | discord.Member, profile: UserProfileSchema) -> discord.Embed:
        """Build the profile display embed."""
        embed = discord.Embed(title=f"{user.display_name}'s Profile")
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="Name", value=profile.preferred_name, inline=True)
        embed.add_field(name="Major", value=profile.major, inline=True)
        embed.add_field(name="Grad Year", value=str(profile.graduation_year), inline=True)
        embed.add_field(name="Email", value=profile.school_email, inline=True)
        embed.add_field(name="Minor", value=profile.minor or "N/A", inline=True)
        embed.add_field(name="Description", value=profile.description or "N/A", inline=False)

        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Student ID: *****{profile.student_id[-4:]} • Last updated: {now}")
        return embed
