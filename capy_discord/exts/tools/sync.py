"""Command synchronization cog.

This module handles synchronizing application commands with Discord:
- Manual sync via command
- Slash command sync
- Global sync
- Debug guild sync (when DEBUG_GUILD_ID is configured)
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.config import settings


class Sync(commands.Cog):
    """Cog for synchronizing application commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Sync cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Sync cog initialized")

    async def _sync_commands(self) -> tuple[list[app_commands.AppCommand], list[app_commands.AppCommand] | None]:
        """Synchronize commands with Discord.

        Returns:
            A tuple of (global_commands, guild_commands).
            guild_commands is None if no debug_guild_id is configured.
        """
        # Sync global commands
        global_synced: list[app_commands.AppCommand] = await self.bot.tree.sync()
        self.log.info("Synced %d global commands: %s", len(global_synced), [c.name for c in global_synced])

        # Sync debug guild if configured (for guild-specific commands like /hotswap)
        guild_synced: list[app_commands.AppCommand] | None = None
        if settings.debug_guild_id:
            guild = discord.Object(id=settings.debug_guild_id)
            guild_synced = await self.bot.tree.sync(guild=guild)
            self.log.info(
                "Synced %d commands to debug guild %s: %s",
                len(guild_synced),
                settings.debug_guild_id,
                [c.name for c in guild_synced],
            )

        return global_synced, guild_synced

    @commands.command(name="sync", hidden=True)
    async def sync(self, ctx: commands.Context[commands.Bot], spec: str | None = None) -> None:
        """Sync commands manually with "!" prefix (owner only)."""
        try:
            if spec in [".", "guild"]:
                if ctx.guild is None:
                    await ctx.send("This command must be used in a guild.")
                    return
                # Instant sync to current guild
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
                description = f"Synced {len(synced)} commands to **current guild**."
            elif spec == "clear":
                if ctx.guild is None:
                    await ctx.send("This command must be used in a guild.")
                    return
                # Clear guild commands
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                description = "Cleared commands for **current guild**."
            else:
                # Global sync + debug guild sync
                global_synced, guild_synced = await self._sync_commands()
                description = f"Synced {len(global_synced)} commands **globally** (may take 1h)."
                if guild_synced is not None:
                    description += f"\nSynced {len(guild_synced)} commands to **debug guild** (instant)."

            self.log.info("!sync invoked by %s: %s", ctx.author.id, description)
            await ctx.send(description)

        except Exception:
            self.log.exception("!sync attempted with error")
            await ctx.send("Sync failed. Check logs.")

    @app_commands.command(name="sync", description="Sync application commands")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_slash(self, interaction: discord.Interaction) -> None:
        """Sync commands via slash command."""
        try:
            await interaction.response.defer(ephemeral=True)

            global_synced, guild_synced = await self._sync_commands()

            description = f"Synced {len(global_synced)} global commands: {[cmd.name for cmd in global_synced]}"
            if guild_synced is not None:
                description += (
                    f"\nSynced {len(guild_synced)} debug guild commands: {[cmd.name for cmd in guild_synced]}"
                )

            self.log.info("/sync invoked user: %s guild: %s", interaction.user.id, interaction.guild_id)
            await interaction.followup.send(description)

        except Exception:
            self.log.exception("/sync attempted user with error")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "We're sorry, this interaction failed. Please contact an admin.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "We're sorry, this interaction failed. Please contact an admin.",
                    ephemeral=True,
                )


async def setup(bot: commands.Bot) -> None:
    """Set up the Sync cog."""
    await bot.add_cog(Sync(bot))
