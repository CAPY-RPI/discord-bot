"""Purge command cog.

This module provides a purge command to delete messages from channels
based on count or time duration.
"""

import logging
import re
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.embeds import error_embed, success_embed


class PurgeCog(commands.Cog):
    """Cog for deleting messages permanently based on mode."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Purge cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)

    def parse_duration(self, duration: str) -> timedelta | None:
        """Parse duration string into timedelta. Format: 1d 2h 3m (spaces optional)."""
        if not duration:
            return None

        pattern = r"(?:(\d+)d)?\s*(?:(\d+)h)?\s*(?:(\d+)m)?"
        match = re.match(pattern, duration.strip())
        if not match or not any(match.groups()):
            return None

        days = int(match.group(1) or 0)
        hours = int(match.group(2) or 0)
        minutes = int(match.group(3) or 0)

        return timedelta(days=days, hours=hours, minutes=minutes)

    async def _handle_purge_count(self, amount: int, channel: discord.TextChannel) -> discord.Embed:
        if amount <= 0:
            return error_embed(description="Please specify a number greater than 0.")
        deleted = await channel.purge(limit=amount)
        return success_embed("Purge Complete", f"Successfully deleted {len(deleted)} messages.")

    async def _handle_purge_duration(self, duration: str, channel: discord.TextChannel) -> discord.Embed:
        time_delta = self.parse_duration(duration)
        if not time_delta:
            return error_embed(
                description=(
                    "Invalid duration format.\nUse format: `1d 2h 3m` (e.g., 1d = 1 day, 2h = 2 hours, 3m = 3 minutes)"
                ),
            )

        after_time = datetime.now(UTC) - time_delta
        deleted = await channel.purge(after=after_time)
        return success_embed(
            "Purge Complete", f"Successfully deleted {len(deleted)} messages from the last {duration}."
        )

    @app_commands.command(name="purge", description="Delete messages")
    @app_commands.describe(
        amount="The number of messages to delete (e.g. 10)",
        duration="The timeframe to delete messages from (e.g. 1h30m, 1h 30m)",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self, interaction: discord.Interaction, amount: int | None = None, duration: str | None = None
    ) -> None:
        """Purge messages with optional direct args."""
        if amount is not None and duration is not None:
            await interaction.response.send_message(
                embed=error_embed(description="Please provide **either** an amount **or** a duration, not both."),
                ephemeral=True,
            )
            return

        if amount is None and duration is None:
            await interaction.response.send_message(
                embed=error_embed(description="Please provide either an `amount` or a `duration`."),
                ephemeral=True,
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=error_embed(description="This command can only be used in text channels."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        if amount is not None:
            embed = await self._handle_purge_count(amount, channel)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if duration is not None:
            embed = await self._handle_purge_duration(duration, channel)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return


async def setup(bot: commands.Bot) -> None:
    """Set up the Purge cog."""
    await bot.add_cog(PurgeCog(bot))
