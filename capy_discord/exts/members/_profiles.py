"""Shared in-memory profile helpers for the members domain."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord

if TYPE_CHECKING:
    from discord.ext import commands

    from ._schemas import UserProfileSchema


def get_profile_store(bot: commands.Bot) -> dict[int, UserProfileSchema]:
    """Get or create the shared in-memory profile store."""
    store: dict[int, UserProfileSchema] | None = getattr(bot, "profile_store", None)
    if store is None:
        store = {}
        setattr(bot, "profile_store", store)  # noqa: B010
    return store


def create_profile_embed(user: discord.User | discord.Member, profile: UserProfileSchema) -> discord.Embed:
    """Build the shared profile display embed."""
    embed = discord.Embed(title=f"{user.display_name}'s Profile")
    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(name="Name", value=profile.preferred_name, inline=True)
    embed.add_field(name="Major", value=profile.major, inline=True)
    embed.add_field(name="Grad Year", value=str(profile.graduation_year), inline=True)
    embed.add_field(name="Email", value=profile.school_email, inline=True)
    embed.add_field(name="Minor", value=profile.minor or "N/A", inline=True)
    embed.add_field(name="Description", value=profile.description or "N/A", inline=False)

    now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
    embed.set_footer(text=f"Time Viewed: {now}")
    return embed
