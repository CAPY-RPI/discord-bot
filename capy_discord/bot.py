import logging

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.errors import UserFriendlyError
from capy_discord.exts.core.telemetry import Telemetry
from capy_discord.ui.embeds import error_embed
from capy_discord.utils import EXTENSIONS


class Bot(commands.AutoShardedBot):
    """Bot class for Capy Discord."""

    def _format_missing_permissions(self, permissions: list[str]) -> str:
        """Convert Discord permission names into readable labels."""
        return ", ".join(permission.replace("_", " ").title() for permission in permissions)

    def _get_app_command_error_message(self, error: app_commands.AppCommandError) -> str | None:
        """Return a user-facing error message for expected slash-command failures."""
        actual_error = error.original if isinstance(error, app_commands.CommandInvokeError) else error

        if isinstance(actual_error, UserFriendlyError):
            return actual_error.user_message

        if isinstance(actual_error, app_commands.MissingPermissions):
            permissions = self._format_missing_permissions(actual_error.missing_permissions)
            return f"You need the following permission(s) to run this command: {permissions}."

        if isinstance(actual_error, app_commands.BotMissingPermissions):
            permissions = self._format_missing_permissions(actual_error.missing_permissions)
            return f"I need the following permission(s) to run this command: {permissions}."

        if isinstance(actual_error, app_commands.NoPrivateMessage):
            return "This command can only be used in a server."

        if isinstance(actual_error, app_commands.CheckFailure):
            return "You can't use this command."

        return None

    def _get_prefix_error_message(self, error: commands.CommandError) -> str | None:
        """Return a user-facing error message for expected prefix-command failures."""
        actual_error = error.original if isinstance(error, commands.CommandInvokeError) else error

        if isinstance(actual_error, UserFriendlyError):
            return actual_error.user_message

        if isinstance(actual_error, commands.MissingPermissions):
            permissions = self._format_missing_permissions(actual_error.missing_permissions)
            return f"You need the following permission(s) to run this command: {permissions}."

        if isinstance(actual_error, commands.BotMissingPermissions):
            permissions = self._format_missing_permissions(actual_error.missing_permissions)
            return f"I need the following permission(s) to run this command: {permissions}."

        if isinstance(actual_error, commands.NoPrivateMessage):
            return "This command can only be used in a server."

        if isinstance(actual_error, commands.CheckFailure):
            return "You can't use this command."

        return None

    async def setup_hook(self) -> None:
        """Run before the bot starts."""
        self.log = logging.getLogger(__name__)
        self.tree.on_error = self.on_tree_error  # type: ignore
        await self.load_extensions()

    def _get_logger_for_command(
        self, command: app_commands.Command | app_commands.ContextMenu | commands.Command | None
    ) -> logging.Logger:
        if command and hasattr(command, "module") and command.module:
            return logging.getLogger(command.module)
        return self.log

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Handle errors in slash commands."""
        # Track all failures in telemetry (both user-friendly and unexpected)
        telemetry = self.get_cog("Telemetry")
        if isinstance(telemetry, Telemetry):
            telemetry.log_command_failure(interaction, error)

        message = self._get_app_command_error_message(error)
        if message is not None:
            embed = error_embed(description=message)
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
        message = self._get_prefix_error_message(error)
        if message is not None:
            embed = error_embed(description=message)
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
