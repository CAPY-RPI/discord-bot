"""Ping command cog.

This module provides a simple ping command to check bot latency.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands


class Ping(commands.Cog):
    """Cog for ping command."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Ping cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Ping cog initialized")

    @app_commands.command(name="ping", description="Shows the bot's latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Respond with the bot's latency."""
        try:
            latency = round(self.bot.latency * 1000)  # in ms
            message = f"Pong! {latency} ms Latency!"
            embed = discord.Embed(title="Ping", description=message)
            self.log.info("/ping invoked user: %s guild: %s", interaction.user.id, interaction.guild_id)

            await interaction.response.send_message(embed=embed)

        except Exception:
            self.log.exception("/ping attempted user")
            await interaction.response.send_message("We're sorry, this interaction failed. Please contact an admin.")


async def setup(bot: commands.Bot) -> None:
    """Set up the Ping cog."""
    await bot.add_cog(Ping(bot))
