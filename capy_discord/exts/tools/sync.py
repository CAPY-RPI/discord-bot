"""Command synchronization cog.

This module handles synchronizing application commands with Discord:
- Manual sync via command
- Slash command sync
- Global sync

#TODO: Add sync status tracking
"""

import discord
from discord import app_commands
from discord.ext import commands

import capy_discord


class SyncCog(commands.Cog):
    """Cog for synchronizing application commands."""

    async def _sync_commands(self) -> list[discord.app_commands.AppCommand]:
        """Synchronize commands with Discord.

        Returns:
            List of synced commands

        #! Note: This operation can be rate limited
        """
        synced_commands: list[discord.app_commands.AppCommand] = await capy_discord.instance.tree.sync()
        return synced_commands

    @commands.command(name="sync", hidden=True)
    async def sync(self, ctx: commands.Context[commands.Bot]) -> None:
        """Sync commands manually (owner only)."""
        try:
            synced = await self._sync_commands()

            description = f"Synced {len(synced)} commands: {[cmd.name for cmd in synced]}"
            await ctx.send(description)

        except Exception as e:
            await ctx.send(f"Failed to sync commands: {e}")

    @app_commands.command(name="sync", description="Sync application commands")
    async def sync_slash(self, interaction: discord.Interaction) -> None:
        """Sync commands via slash command."""
        try:
            synced = await self._sync_commands()

            description = f"Synced {len(synced)} commands: {[cmd.name for cmd in synced]}"
            await interaction.response.send_message(description)

        except Exception as e:
            await interaction.response.send_message(f"Failed to sync commands: {e}")


async def setup(bot: commands.Bot) -> None:
    """Set up the Sync cog."""
    await bot.add_cog(SyncCog(bot))
