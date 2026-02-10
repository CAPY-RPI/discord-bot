import logging

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.ui.forms import ModelModal
from capy_discord.ui.views import BaseView

from ._guild_schemas import (
    AnnouncementChannelForm,
    ChannelSettingsForm,
    FeedbackChannelForm,
    GuildSettings,
    RoleSettingsForm,
    WelcomeMessageForm,
)


class SettingsMenuView(BaseView):
    """Button-based view that opens ModelModal forms for different guild settings."""

    def __init__(self, cog: "GuildCog") -> None:
        """Initialize the settings menu view."""
        super().__init__(timeout=120)
        self.cog = cog

    @ui.button(label="Channels", style=discord.ButtonStyle.blurple)
    async def channels(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to configure channel destinations."""
        modal = ModelModal(
            model_cls=ChannelSettingsForm,
            callback=self.cog._handle_channels,
            title="Channel Settings",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Roles", style=discord.ButtonStyle.blurple)
    async def roles(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to configure role scopes."""
        modal = ModelModal(
            model_cls=RoleSettingsForm,
            callback=self.cog._handle_roles,
            title="Role Settings",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Announcement Channel", style=discord.ButtonStyle.green)
    async def announcement(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to set the announcement channel."""
        modal = ModelModal(
            model_cls=AnnouncementChannelForm,
            callback=self.cog._handle_announcement,
            title="Announcement Channel",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Feedback Channel", style=discord.ButtonStyle.green)
    async def feedback(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to set the feedback channel."""
        modal = ModelModal(
            model_cls=FeedbackChannelForm,
            callback=self.cog._handle_feedback,
            title="Feedback Channel",
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="Onboarding Welcome", style=discord.ButtonStyle.gray)
    async def onboarding(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open modal to edit the onboarding welcome message."""
        guild_id = interaction.guild.id if interaction.guild else None
        default_msg = None
        if guild_id and guild_id in self.cog._store:
            default_msg = self.cog._store[guild_id].onboarding_welcome
        modal = ModelModal(
            model_cls=WelcomeMessageForm,
            callback=self.cog._handle_welcome,
            title="Onboarding Welcome",
            initial_data={"message": default_msg} if default_msg else None,
        )
        await interaction.response.send_modal(modal)


class GuildCog(commands.Cog):
    """Guild settings management for the capy_discord framework."""

    guild_group = app_commands.Group(name="guild", description="Guild settings commands")

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the GuildCog and attach an in-memory settings store to the bot."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        # In-memory store keyed by guild_id, attached to the bot instance
        # so it persists across cog reloads.
        store: dict[int, GuildSettings] | None = getattr(bot, "guild_settings_store", None)
        if store is None:
            store = {}
            setattr(bot, "guild_settings_store", store)  # noqa: B010
        self._store = store

    def _ensure_settings(self, guild_id: int) -> GuildSettings:
        """Return existing settings for a guild or create defaults."""
        if guild_id not in self._store:
            self._store[guild_id] = GuildSettings()
        return self._store[guild_id]

    # -- ModelModal callbacks ------------------------------------------------
    # Each callback receives (interaction, validated_pydantic_model).

    async def _handle_channels(self, interaction: discord.Interaction, form: ChannelSettingsForm) -> None:
        """Persist channel settings from validated form data."""
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        settings = self._ensure_settings(interaction.guild.id)
        settings.reports_channel = int(form.reports) if form.reports.isdigit() else None
        settings.announcements_channel = int(form.announcements) if form.announcements.isdigit() else None
        settings.feedback_channel = int(form.feedback) if form.feedback.isdigit() else None
        await interaction.response.send_message("✅ Channel settings saved.", ephemeral=True)

    async def _handle_roles(self, interaction: discord.Interaction, form: RoleSettingsForm) -> None:
        """Persist role settings from validated form data."""
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        settings = self._ensure_settings(interaction.guild.id)
        settings.admin_role = form.admin or None
        settings.member_role = form.member or None
        await interaction.response.send_message("✅ Role settings saved.", ephemeral=True)

    async def _handle_announcement(self, interaction: discord.Interaction, form: AnnouncementChannelForm) -> None:
        """Persist the announcement channel from validated form data."""
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        settings = self._ensure_settings(interaction.guild.id)
        settings.announcements_channel = int(form.channel) if form.channel.isdigit() else None
        await interaction.response.send_message("✅ Announcement channel saved.", ephemeral=True)

    async def _handle_feedback(self, interaction: discord.Interaction, form: FeedbackChannelForm) -> None:
        """Persist the feedback channel from validated form data."""
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        settings = self._ensure_settings(interaction.guild.id)
        settings.feedback_channel = int(form.channel) if form.channel.isdigit() else None
        await interaction.response.send_message("✅ Feedback channel saved.", ephemeral=True)

    async def _handle_welcome(self, interaction: discord.Interaction, form: WelcomeMessageForm) -> None:
        """Persist the onboarding welcome message from validated form data."""
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        settings = self._ensure_settings(interaction.guild.id)
        settings.onboarding_welcome = form.message or None
        await interaction.response.send_message("✅ Welcome message updated.", ephemeral=True)

    # -- Slash command -------------------------------------------------------

    @guild_group.command(name="settings")
    @app_commands.guild_only()
    async def settings(self, interaction: discord.Interaction) -> None:
        """Open the guild settings menu."""
        if not isinstance(interaction.guild, discord.Guild):
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        view = SettingsMenuView(self)
        await view.reply(interaction, content="Guild settings — choose a category to edit:", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Guild cog."""
    await bot.add_cog(GuildCog(bot))
