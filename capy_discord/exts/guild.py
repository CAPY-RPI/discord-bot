import contextlib
import logging
from collections.abc import Callable
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.ui.modal import CallbackModal

from ._guild_schemas import GuildSettings


class _ValueModal(CallbackModal):
    """Simple single-field modal used for editing a single value."""

    def __init__(
        self,
        callback: Callable[[discord.Interaction, "_ValueModal"], Any],
        title: str,
        label: str,
        placeholder: str = "",
    ) -> None:
        """Initialize the value modal.

        Args:
            callback: Coroutine to call on submit.
            title: Modal title to display to the user.
            label: Label for the single TextInput field.
            placeholder: Placeholder text for the input.
        """
        super().__init__(callback=callback, title=title)
        self.input = ui.TextInput(label=label, placeholder=placeholder, required=False)
        self.add_item(self.input)


class _WelcomeModal(CallbackModal):
    """Modal for editing the onboarding welcome message."""

    def __init__(
        self, callback: Callable[[discord.Interaction, "_WelcomeModal"], Any], default: str | None = None
    ) -> None:
        """Initialize the welcome modal."""
        super().__init__(callback=callback, title="Edit Welcome Message")
        self.welcome = ui.TextInput(
            label="Welcome Message",
            style=discord.TextStyle.long,
            default=default or "",
            required=False,
        )
        self.add_item(self.welcome)


class SettingsMenuView(ui.View):
    """Button-based view that opens modals for different guild settings."""

    def __init__(self, cog: "GuildCog") -> None:
        """Initialize the settings menu view."""
        super().__init__(timeout=120)
        self.cog = cog

    @ui.button(label="Channels", style=discord.ButtonStyle.blurple)
    async def channels(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to set a channel value."""
        modal = _ValueModal(
            callback=self.cog._handle_channel_modal,
            title="Set Channel",
            label="Channel (mention or ID)",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Roles", style=discord.ButtonStyle.blurple)
    async def roles(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to set a role value."""
        modal = _ValueModal(
            callback=self.cog._handle_role_modal,
            title="Set Role",
            label="Role (mention or ID)",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Announcement Channel", style=discord.ButtonStyle.green)
    async def announcement(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to set the announcement channel."""
        modal = _ValueModal(
            callback=self.cog._handle_announcement_modal,
            title="Announcement Channel",
            label="Channel (mention or ID)",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Feedback Channel", style=discord.ButtonStyle.green)
    async def feedback(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to set the feedback channel."""
        modal = _ValueModal(
            callback=self.cog._handle_feedback_modal,
            title="Feedback Channel",
            label="Channel (mention or ID)",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Onboarding Welcome", style=discord.ButtonStyle.gray)
    async def onboarding(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to edit the onboarding welcome message."""
        guild_id = interaction.guild.id if interaction.guild else None
        default = None
        if guild_id and guild_id in self.cog._store:
            default = self.cog._store[guild_id].onboarding_welcome
        modal = _WelcomeModal(callback=self.cog._handle_welcome_modal, default=default)
        await interaction.response.send_modal(modal)


class GuildCog(commands.Cog):
    """Guild settings management for the new capy_discord framework."""

    guild_group = app_commands.Group(name="guild", description="Guild settings commands")

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the GuildCog and in-memory settings store on the bot."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        # In-memory store keyed by guild_id, attached to the bot instance
        # so it persists across cog reloads.
        store: dict[int, GuildSettings] | None = getattr(bot, "guild_settings_store", None)
        if store is None:
            store = {}
            setattr(bot, "guild_settings_store", store)  # noqa: B010
        self._store = store

    async def _ensure_settings(self, guild_id: int) -> GuildSettings:
        if guild_id not in self._store:
            self._store[guild_id] = GuildSettings()
        return self._store[guild_id]

    async def _handle_channel_modal(self, interaction: discord.Interaction, modal: _ValueModal) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        value = modal.input.value.strip()
        settings = await self._ensure_settings(interaction.guild.id)
        # store raw value; integration with real DB/validation should parse mentions/IDs
        try:
            settings.channels.reports = int(value) if value.isdigit() else None
        except Exception:
            settings.channels.reports = None
        await interaction.response.send_message("Channel value saved (reports).", ephemeral=True)

    async def _handle_role_modal(self, interaction: discord.Interaction, modal: _ValueModal) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        value = modal.input.value.strip()
        settings = await self._ensure_settings(interaction.guild.id)
        settings.roles.admin = value or None
        await interaction.response.send_message("Role value saved (admin).", ephemeral=True)

    async def _handle_announcement_modal(self, interaction: discord.Interaction, modal: _ValueModal) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        value = modal.input.value.strip()
        settings = await self._ensure_settings(interaction.guild.id)
        try:
            settings.channels.announcements = int(value) if value.isdigit() else None
        except Exception:
            settings.channels.announcements = None
        await interaction.response.send_message("Announcement channel saved.", ephemeral=True)

    async def _handle_feedback_modal(self, interaction: discord.Interaction, modal: _ValueModal) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        value = modal.input.value.strip()
        settings = await self._ensure_settings(interaction.guild.id)
        try:
            settings.channels.feedback = int(value) if value.isdigit() else None
        except Exception:
            settings.channels.feedback = None
        await interaction.response.send_message("Feedback channel saved.", ephemeral=True)

    async def _handle_welcome_modal(self, interaction: discord.Interaction, modal: _WelcomeModal) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        value = modal.welcome.value.strip()
        settings = await self._ensure_settings(interaction.guild.id)
        settings.onboarding_welcome = value or None
        await interaction.response.send_message("Welcome message updated.", ephemeral=True)

    @guild_group.command(name="settings")
    @app_commands.guild_only()
    async def settings(self, interaction: discord.Interaction) -> None:
        """Open the guild settings menu."""
        if not isinstance(interaction.guild, discord.Guild):
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        view = SettingsMenuView(self)
        await interaction.response.send_message(
            "Guild settings — choose a category to edit:", ephemeral=True, view=view
        )


async def setup(bot: commands.Bot) -> None:
    """Set up the Guild cog and register app command group."""
    cog = GuildCog(bot)
    await bot.add_cog(cog)
    # Register the group to the bot's tree so it appears as `/guild settings`
    with contextlib.suppress(Exception):
        bot.tree.add_command(cog.guild_group)
