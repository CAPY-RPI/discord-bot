import logging

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.config import settings
from capy_discord.database import BackendClientConfig, close_database_pool, init_database_pool
from capy_discord.errors import UserFriendlyError
from capy_discord.exts.core.telemetry import Telemetry
from capy_discord.ui.embeds import error_embed
from capy_discord.utils import EXTENSIONS


class Bot(commands.AutoShardedBot):
    """Bot class for Capy Discord."""

    async def setup_hook(self) -> None:
        """Run before the bot starts."""
        self.log = logging.getLogger(__name__)
        await init_database_pool(
            settings.backend_api_base_url,
            config=BackendClientConfig(
                bot_token=settings.backend_api_bot_token,
                auth_cookie=settings.backend_api_auth_cookie,
                timeout_seconds=settings.backend_api_timeout_seconds,
                max_connections=settings.backend_api_max_connections,
                max_keepalive_connections=settings.backend_api_max_keepalive_connections,
            ),
        )
        self.log.info("Backend API client initialized for environment: %s", settings.backend_environment)
        self.tree.on_error = self.on_tree_error  # type: ignore
        await self.load_extensions()

    async def close(self) -> None:
        """Close bot resources before shutting down."""
        await close_database_pool()
        await super().close()

    def _get_logger_for_command(
        self, command: app_commands.Command | app_commands.ContextMenu | commands.Command | None
    ) -> logging.Logger:
        if command and hasattr(command, "module") and command.module:
            return logging.getLogger(command.module)
        return self.log

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Handle errors in slash commands."""
        # Unpack CommandInvokeError to get the original exception
        actual_error = error
        if isinstance(error, app_commands.CommandInvokeError):
            actual_error = error.original

        # Track all failures in telemetry (both user-friendly and unexpected)
        telemetry = self.get_cog("Telemetry")
        if isinstance(telemetry, Telemetry):
            telemetry.log_command_failure(interaction, error)

        if isinstance(actual_error, UserFriendlyError):
            embed = error_embed(description=actual_error.user_message)
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Generic error handling
        logger = self._get_logger_for_command(interaction.command)
        logger.exception("Slash command error: %s", error)
        embed = error_embed(description="An unexpected error occurred. Please try again later.")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Handle errors in prefix commands."""
        actual_error = error
        if isinstance(error, commands.CommandInvokeError):
            actual_error = error.original

        if isinstance(actual_error, UserFriendlyError):
            embed = error_embed(description=actual_error.user_message)
            await ctx.send(embed=embed)
            return

        # Generic error handling
        logger = self._get_logger_for_command(ctx.command)
        logger.exception("Prefix command error: %s", error)
        embed = error_embed(description="An unexpected error occurred. Please try again later.")
        await ctx.send(embed=embed)

    async def load_extensions(self) -> None:
        """Load all enabled extensions."""
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                self.log.info("Loaded extension: %s", extension)
            except Exception:
                self.log.exception("Failed to load extension: %s", extension)
