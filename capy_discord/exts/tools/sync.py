"""Command synchronization cog.

This module handles synchronizing application commands with Discord:
- Manual sync via command
- Slash command sync
- Global sync
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import capy_discord


class Sync(commands.Cog):
    """Cog for synchronizing application commands."""

    def __init__(self) -> None:
        """Initialize the Sync cog."""
        self.logger = logging.getLogger(__name__)

    async def _sync_commands(self) -> list[discord.app_commands.AppCommand]:
        """Synchronize commands with Discord."""
        synced_commands: list[discord.app_commands.AppCommand] = await capy_discord.instance.tree.sync()
        self.logger.info("_sync_commands internal: %s", synced_commands)
        return synced_commands

    @commands.command(name="sync", hidden=True)
    async def sync(self, ctx: commands.Context[commands.Bot]) -> None:
        """Sync commands manually (owner only)."""
        try:
            synced = await self._sync_commands()

            description = f"Synced {len(synced)} commands: {[cmd.name for cmd in synced]}"
            self.logger.info("!sync invoked user: %s guild: %s", ctx.author.id, ctx.guild.id)
            await ctx.send(description)

        except Exception:
            self.logger.exception("!sync attempted with error")
            await ctx.send("We're sorry, this interaction failed. Please contact an admin.")

    @app_commands.command(name="sync", description="Sync application commands")
    async def sync_slash(self, interaction: discord.Interaction) -> None:
        """Sync commands via slash command."""
        try:
            synced = await self._sync_commands()
            description = f"Synced {len(synced)} commands: {[cmd.name for cmd in synced]}"
            self.logger.info("/sync invoked user: %s guild: %s", interaction.user.id, interaction.guild_id)
            await interaction.response.send_message(description)

        except Exception:
            self.logger.exception("/sync attempted user with error")
            await interaction.response.send_message("We're sorry, this interaction failed. Please contact an admin.")


async def setup(bot: commands.Bot) -> None:
    """Set up the Sync cog."""
    await bot.add_cog(Sync())
