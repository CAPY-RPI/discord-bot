import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.embeds import error_embed

from ._guild_schemas import (
    GuildSettings,
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

    guild = app_commands.Group(name="guild", description="Manage guild settings (single-line)")

    @guild.command(name="channels", description="Set channel IDs in one line")
    @app_commands.guild_only()
    @app_commands.describe(
        reports="Reports channel",
        announcements="Announcements channel",
        feedback="Feedback channel",
    )
    async def guild_channels(
        self,
        interaction: discord.Interaction,
        reports: discord.TextChannel | None = None,
        announcements: discord.TextChannel | None = None,
        feedback: discord.TextChannel | None = None,
    ) -> None:
        """Update channels for reporting, announcement, and feedback purposes."""
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=error_embed(description="This command can only be used in a server (not in DMs)."),
                ephemeral=True,
            )
            return
        settings = self._ensure_settings(interaction.guild.id)
        if reports is not None:
            settings.reports_channel = reports.id
        if announcements is not None:
            settings.announcements_channel = announcements.id
        if feedback is not None:
            settings.feedback_channel = feedback.id
        await interaction.response.send_message("✅ Channel settings saved.", ephemeral=True)

    @guild.command(name="channels-clear", description="Clear saved channel IDs")
    @app_commands.guild_only()
    @app_commands.describe(target="Which channel setting to clear")
    @app_commands.choices(
        target=[
            app_commands.Choice(name="reports", value="reports"),
            app_commands.Choice(name="announcements", value="announcements"),
            app_commands.Choice(name="feedback", value="feedback"),
            app_commands.Choice(name="all", value="all"),
        ]
    )
    async def guild_channels_clear(
        self,
        interaction: discord.Interaction,
        target: Literal["reports", "announcements", "feedback", "all"],
    ) -> None:
        """Clear one or all saved channel settings."""
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=error_embed(description="This command can only be used in a server (not in DMs)."),
                ephemeral=True,
            )
            return

        settings = self._ensure_settings(interaction.guild.id)
        if target in {"reports", "all"}:
            settings.reports_channel = None
        if target in {"announcements", "all"}:
            settings.announcements_channel = None
        if target in {"feedback", "all"}:
            settings.feedback_channel = None
        await interaction.response.send_message(f"✅ Cleared channel setting(s): {target}.", ephemeral=True)

    @guild.command(name="roles", description="Set roles in one line")
    @app_commands.guild_only()
    @app_commands.describe(admin="Admin role", member="Member role")
    async def guild_roles(
        self,
        interaction: discord.Interaction,
        admin: discord.Role | None = None,
        member: discord.Role | None = None,
    ) -> None:
        """Give users roles."""
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=error_embed(description="This command can only be used in a server (not in DMs)."),
                ephemeral=True,
            )
            return
        settings = self._ensure_settings(interaction.guild.id)
        if admin is not None:
            settings.admin_role = str(admin.id)
        if member is not None:
            member_id = str(member.id)
            if member_id not in settings.member_roles:
                settings.member_roles.append(member_id)
        await interaction.response.send_message("✅ Role settings saved.", ephemeral=True)

    @guild.command(name="roles-clear", description="Clear saved role settings")
    @app_commands.guild_only()
    @app_commands.describe(target="Which role setting to clear")
    @app_commands.choices(
        target=[
            app_commands.Choice(name="admin", value="admin"),
            app_commands.Choice(name="member_roles", value="member_roles"),
            app_commands.Choice(name="all", value="all"),
        ]
    )
    async def guild_roles_clear(
        self,
        interaction: discord.Interaction,
        target: Literal["admin", "member_roles", "all"],
    ) -> None:
        """Clear one or all saved role settings."""
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=error_embed(description="This command can only be used in a server (not in DMs)."),
                ephemeral=True,
            )
            return

        settings = self._ensure_settings(interaction.guild.id)
        if target in {"admin", "all"}:
            settings.admin_role = None
        if target in {"member_roles", "all"}:
            settings.member_roles.clear()
        await interaction.response.send_message(f"✅ Cleared role setting(s): {target}.", ephemeral=True)

    @guild.command(name="onboarding", description="Set the onboarding welcome message")
    @app_commands.guild_only()
    @app_commands.describe(message="Welcome message shown during onboarding. Use {user} to reference interacting user.")
    async def guild_onboarding(self, interaction: discord.Interaction, message: str | None = None) -> None:
        """Customize onboarding message."""
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=error_embed(description="This command can only be used in a server (not in DMs)."),
                ephemeral=True,
            )
            return
        settings = self._ensure_settings(interaction.guild.id)

        settings.onboarding_welcome = message or None

        if not settings.onboarding_welcome:
            await interaction.response.send_message(
                "✅ Welcome message cleared. (No onboarding message will be sent.)",
                ephemeral=True,
            )
            return

        # A simple "test run" preview:
        # - let you use {user} in the template
        preview = settings.onboarding_welcome.replace("{user}", interaction.user.mention)

        # Send an ephemeral preview so it doesn't spam the server
        await interaction.response.send_message(
            "✅ Welcome message updated. Here's a test preview (ephemeral):",
            ephemeral=True,
        )
        await interaction.followup.send(preview, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=True))

    @guild.command(name="summary", description="Return a summary of current guild settings")
    @app_commands.guild_only()
    async def guild_summary(self, interaction: discord.Interaction) -> None:
        """Return current guild settings."""
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=error_embed(description="This command can only be used in a server (not in DMs)."),
                ephemeral=True,
            )
            return

        guild = interaction.guild
        settings = self._ensure_settings(guild.id)

        def channel_mention(channel_id: int | None) -> str:
            if not channel_id:
                return "Not set"
            ch = guild.get_channel(channel_id)
            return ch.mention if ch else f"<#{channel_id}> (not found)"

        def role_mention(role_id: int | str | None) -> str:
            if not role_id:
                return "Not set"
            normalized_role_id = int(role_id) if isinstance(role_id, str) else role_id
            role = guild.get_role(normalized_role_id)
            return role.mention if role else f"<@&{normalized_role_id}> (not found)"

        announcements = channel_mention(getattr(settings, "announcements_channel", None))
        reports = channel_mention(getattr(settings, "reports_channel", None))
        feedback = channel_mention(getattr(settings, "feedback_channel", None))

        admin_role = role_mention(getattr(settings, "admin_role", None))
        member_roles: list[str] = getattr(settings, "member_roles", [])
        member_role = ", ".join(role_mention(role_id) for role_id in member_roles) if member_roles else "Not set"

        onboarding = settings.onboarding_welcome or "Not set"

        summary = (
            "**Current Guild Settings**\n"
            f"Announcements Channel: {announcements}\n"
            f"Reports Channel: {reports}\n"
            f"Feedback Channel: {feedback}\n"
            f"Admin Role: {admin_role}\n"
            f"Member Roles: {member_role}\n"
            f"Onboarding Welcome: {onboarding}"
        )

        await interaction.response.send_message(summary, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Guild cog."""
    await bot.add_cog(GuildCog(bot))
