import logging

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.forms import ModelModal

from ._schemas import (
    AnnouncementChannelForm,
    ChannelSettingsForm,
    FeedbackChannelForm,
    GuildSettings,
    RoleSettingsForm,
    WelcomeMessageForm,
)


class GuildCog(commands.Cog):
    """Guild settings management for the capy_discord framework."""

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

    # -- /guild command with action choices ---------------------------------

    @app_commands.command(name="guild", description="Manage guild settings")
    @app_commands.describe(action="The setting to configure")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="channels", value="channels"),
            app_commands.Choice(name="roles", value="roles"),
            app_commands.Choice(name="announcement", value="announcement"),
            app_commands.Choice(name="feedback", value="feedback"),
            app_commands.Choice(name="onboarding", value="onboarding"),
        ]
    )
    @app_commands.guild_only()
    async def guild(self, interaction: discord.Interaction, action: str) -> None:
        """Handle guild settings actions based on the selected choice."""
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return

        settings = self._ensure_settings(interaction.guild.id)

        if action == "channels":
            await self._open_channels(interaction, settings)
        elif action == "roles":
            await self._open_roles(interaction, settings)
        elif action == "announcement":
            await self._open_announcement(interaction, settings)
        elif action == "feedback":
            await self._open_feedback(interaction, settings)
        elif action == "onboarding":
            await self._open_onboarding(interaction, settings)

    # -- Modal launchers -----------------------------------------------------

    async def _open_channels(self, interaction: discord.Interaction, settings: GuildSettings) -> None:
        """Launch the channel settings modal pre-filled with current values."""
        initial = {
            "reports": str(settings.reports_channel) if settings.reports_channel else None,
            "announcements": str(settings.announcements_channel) if settings.announcements_channel else None,
            "feedback": str(settings.feedback_channel) if settings.feedback_channel else None,
        }
        modal = ModelModal(
            model_cls=ChannelSettingsForm,
            callback=self._handle_channels,
            title="Channel Settings",
            initial_data=initial,
        )
        await interaction.response.send_modal(modal)

    async def _open_roles(self, interaction: discord.Interaction, settings: GuildSettings) -> None:
        """Launch the role settings modal pre-filled with current values."""
        initial = {"admin": settings.admin_role, "member": settings.member_role}
        modal = ModelModal(
            model_cls=RoleSettingsForm, callback=self._handle_roles, title="Role Settings", initial_data=initial
        )
        await interaction.response.send_modal(modal)

    async def _open_announcement(self, interaction: discord.Interaction, settings: GuildSettings) -> None:
        """Launch the announcement channel modal pre-filled with current value."""
        initial = {"channel": str(settings.announcements_channel) if settings.announcements_channel else None}
        modal = ModelModal(
            model_cls=AnnouncementChannelForm,
            callback=self._handle_announcement,
            title="Announcement Channel",
            initial_data=initial,
        )
        await interaction.response.send_modal(modal)

    async def _open_feedback(self, interaction: discord.Interaction, settings: GuildSettings) -> None:
        """Launch the feedback channel modal pre-filled with current value."""
        initial = {"channel": str(settings.feedback_channel) if settings.feedback_channel else None}
        modal = ModelModal(
            model_cls=FeedbackChannelForm,
            callback=self._handle_feedback,
            title="Feedback Channel",
            initial_data=initial,
        )
        await interaction.response.send_modal(modal)

    async def _open_onboarding(self, interaction: discord.Interaction, settings: GuildSettings) -> None:
        """Launch the onboarding welcome modal pre-filled with current value."""
        initial = {"message": settings.onboarding_welcome} if settings.onboarding_welcome else None
        modal = ModelModal(
            model_cls=WelcomeMessageForm,
            callback=self._handle_welcome,
            title="Onboarding Welcome",
            initial_data=initial,
        )
        await interaction.response.send_modal(modal)

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


async def setup(bot: commands.Bot) -> None:
    """Set up the Guild cog."""
    await bot.add_cog(GuildCog(bot))
