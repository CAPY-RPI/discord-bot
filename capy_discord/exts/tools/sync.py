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
        self.log = logging.getLogger(__name__)
        self.log.info("Sync cog initialized")

    async def _sync_commands(self) -> list[discord.app_commands.AppCommand]:
        """Synchronize commands with Discord."""
        if capy_discord.instance is None:
            self.log.error("Bot instance is None during sync")
            return []

        synced_commands: list[discord.app_commands.AppCommand] = await capy_discord.instance.tree.sync()
        self.log.info("_sync_commands internal: %s", synced_commands)
        return synced_commands

    # * admin locked command
    @commands.command(name="sync", hidden=True)
    async def sync(self, ctx: commands.Context[commands.Bot], spec: str | None = None) -> None:
        """Sync commands manually with "!" prefix (owner only)."""
        try:
            if spec in [".", "guild"]:
                # Instant sync to current guild
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
                description = f"Synced {len(synced)} commands to **current guild**."
            elif spec == "clear":
                # Clear guild commands
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                description = "Cleared commands for **current guild**."
            else:
                # Global sync
                synced = await ctx.bot.tree.sync()
                description = f"Synced {len(synced)} commands **globally** (may take 1h)."

            self.log.info("!sync invoked by %s: %s", ctx.author.id, description)
            await ctx.send(description)

        except Exception:
            self.log.exception("!sync attempted with error")
            await ctx.send("Sync failed. Check logs.")

    # * this should be owner/admin only in prod
    @app_commands.command(name="sync", description="Sync application commands")
    async def sync_slash(self, interaction: discord.Interaction) -> None:
        """Sync commands via slash command."""
        try:
            if capy_discord.instance is None:
                # Log error and return early
                self.log.error("/sync failed: Bot instance is None")
                await interaction.response.send_message("Internal error: Bot instance not found.", ephemeral=True)
                return

            synced = await capy_discord.instance.tree.sync()
            description = f"Synced {len(synced)} commands: {[cmd.name for cmd in synced]}"
            self.log.info("/sync invoked user: %s guild: %s", interaction.user.id, interaction.guild_id)
            await interaction.response.send_message(description)

        except Exception:
            self.log.exception("/sync attempted user with error")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "We're sorry, this interaction failed. Please contact an admin."
                )
            else:
                await interaction.followup.send("We're sorry, this interaction failed. Please contact an admin.")


async def setup(bot: commands.Bot) -> None:
    """Set up the Sync cog."""
    await bot.add_cog(Sync())
