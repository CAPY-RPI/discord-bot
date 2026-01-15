"""Command synchronization cog.

This module handles synchronizing application commands with Discord:
- Manual sync via command
- Slash command sync
- Global sync
"""

import logging

import discord
from discord.ext import commands


class Sync(commands.Cog):
    """Cog for synchronizing application commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Sync cog."""
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def _sync_commands(self) -> list[discord.app_commands.AppCommand]:
        """Synchronize commands with Discord."""
        synced_commands: list[discord.app_commands.AppCommand] = await self.bot.tree.sync()
        self.logger.info("_sync_commands internal: %s", synced_commands)
        return synced_commands


async def setup(bot: commands.Bot) -> None:
    """Set up the Sync cog."""
    await bot.add_cog(Sync(bot))
