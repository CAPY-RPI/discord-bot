"""Onboarding and guild setup flow.

This extension provides:
- Guild bootstrap checklist on bot invite.
- In-memory setup configuration via /onboarding commands.
- Member onboarding with rule acknowledgement and role assignment.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from ._schemas import GuildSetupConfig, UserOnboardingState
from ._views import VerifyView


def utc_now() -> datetime:
    """Return timezone-aware current UTC timestamp."""
    return datetime.now(ZoneInfo("UTC"))


class Onboarding(commands.Cog):
    """Cog that manages guild setup and member onboarding."""

    onboarding = app_commands.Group(name="onboarding", description="Configure onboarding and server setup")

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize in-memory stores for setup and user onboarding state."""
        self.bot = bot
        self.log = logging.getLogger(__name__)

        setup_store: dict[int, GuildSetupConfig] | None = getattr(bot, "onboarding_setup_store", None)
        if setup_store is None:
            setup_store = {}
            setattr(bot, "onboarding_setup_store", setup_store)  # noqa: B010

        user_state_store: dict[str, UserOnboardingState] | None = getattr(bot, "onboarding_user_state_store", None)
        if user_state_store is None:
            user_state_store = {}
            setattr(bot, "onboarding_user_state_store", user_state_store)  # noqa: B010

        self._setup_store = setup_store
        self._user_state_store = user_state_store

    def _state_key(self, guild_id: int, user_id: int) -> str:
        """Build deterministic key for user onboarding state."""
        return f"{guild_id}:{user_id}"

    def _ensure_setup(self, guild_id: int) -> GuildSetupConfig:
        """Get or create setup configuration for a guild."""
        if guild_id not in self._setup_store:
            self._setup_store[guild_id] = GuildSetupConfig()
        return self._setup_store[guild_id]

    def _get_user_state(self, guild_id: int, user_id: int) -> UserOnboardingState:
        """Get or create a user's onboarding lifecycle state."""
        key = self._state_key(guild_id, user_id)
        if key not in self._user_state_store:
            self._user_state_store[key] = UserOnboardingState()
        return self._user_state_store[key]

    def _first_public_text_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Return first public text channel where bot can post."""
        bot_member = guild.me
        if bot_member is None and self.bot.user is not None:
            bot_member = guild.get_member(self.bot.user.id)

        if bot_member is None:
            return None

        for channel in guild.text_channels:
            everyone_can_view = channel.permissions_for(guild.default_role).view_channel
            bot_perms = channel.permissions_for(bot_member)
            if everyone_can_view and bot_perms.view_channel and bot_perms.send_messages:
                return channel

        return None

    def _format_role_mentions(self, guild: discord.Guild, role_ids: list[int]) -> str:
        """Format role IDs into readable mentions for summaries."""
        if not role_ids:
            return "Not set"
        parts: list[str] = []
        for role_id in role_ids:
            role = guild.get_role(role_id)
            parts.append(role.mention if role else f"<@&{role_id}> (not found)")
        return ", ".join(parts)

    def _format_channel_mention(self, guild: discord.Guild, channel_id: int | None) -> str:
        """Format channel ID into readable mention for summaries."""
        if channel_id is None:
            return "Not set"
        channel = guild.get_channel(channel_id)
        return channel.mention if channel else f"<#{channel_id}> (not found)"

    def _missing_items(self, config: GuildSetupConfig) -> list[str]:
        """Return required setup items that are still missing."""
        missing: list[str] = []
        if not config.admin_role_ids:
            missing.append("Primary admin role(s)")
        if not config.moderator_role_ids:
            missing.append("Moderator role(s)")
        if config.log_channel_id is None:
            missing.append("Log channel")
        if config.announcement_channel_id is None:
            missing.append("Announcement channel")
        if config.welcome_channel_id is None:
            missing.append("Welcome channel")
        if config.support_channel_id is None:
            missing.append("Support/ticket channel")
        if not config.rules_location:
            missing.append("Rules/verification flow")
        if config.member_role_id is None:
            missing.append("Member role for verified users")
        return missing

    def _build_setup_message(self, guild: discord.Guild) -> str:
        """Build a guild-specific setup checklist message."""
        config = self._ensure_setup(guild.id)
        missing = self._missing_items(config)

        status_lines = [
            f"- Primary admin role(s): {self._format_role_mentions(guild, config.admin_role_ids)}",
            f"- Moderator role(s): {self._format_role_mentions(guild, config.moderator_role_ids)}",
            f"- Log channel: {self._format_channel_mention(guild, config.log_channel_id)}",
            f"- Announcement channel: {self._format_channel_mention(guild, config.announcement_channel_id)}",
            f"- Welcome channel: {self._format_channel_mention(guild, config.welcome_channel_id)}",
            f"- Welcome DMs enabled: {'Yes' if config.welcome_dm_enabled else 'No'}",
            f"- Support/ticket channel: {self._format_channel_mention(guild, config.support_channel_id)}",
            f"- Rules/verification flow: {config.rules_location or 'Not set'}",
            (
                "- Verification member role: "
                f"{self._format_role_mentions(guild, [config.member_role_id]) if config.member_role_id else 'Not set'}"
            ),
        ]

        missing_text = "\n".join(f"- {item}" for item in missing) if missing else "- None"

        return (
            "Thanks for inviting CAPY.\n\n"
            "Run these commands to configure setup:\n"
            "- `/onboarding roles`\n"
            "- `/onboarding channels`\n"
            "- `/onboarding config`\n"
            "- `/onboarding summary`\n\n"
            "**Current Setup Status**\n"
            f"{'\n'.join(status_lines)}\n\n"
            "**Missing Required Items**\n"
            f"{missing_text}\n\n"
            "Data storage is currently in-memory and resets on bot restart."
        )

    def _parse_role_ids(self, raw: str | None, guild: discord.Guild) -> list[int]:
        """Parse role IDs from user input and keep only roles that exist in the guild."""
        if not raw:
            return []
        parsed = {int(role_id) for role_id in re.findall(r"\d+", raw)}
        return sorted([role_id for role_id in parsed if guild.get_role(role_id) is not None])

    async def _send_log_message(self, guild: discord.Guild, config: GuildSetupConfig, message: str) -> None:
        """Send a best-effort onboarding event log message to the configured log channel."""
        if config.log_channel_id is None:
            return

        channel = guild.get_channel(config.log_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            self.log.warning("Failed to send onboarding log message in guild %s: %s", guild.id, exc)

    async def _mark_pending(self, guild_id: int, user_id: int) -> None:
        """Mark user state as pending and increment attempt count."""
        state = self._get_user_state(guild_id, user_id)
        state.status = "pending"
        state.started_at_utc = utc_now()
        state.completed_at_utc = None
        state.attempts += 1

    async def _mark_timed_out(self, guild_id: int, user_id: int) -> None:
        """Reset pending state to new when verification view times out."""
        state = self._get_user_state(guild_id, user_id)
        if state.status == "pending":
            state.status = "new"
            self.log.info("Onboarding timed out for user %s in guild %s", user_id, guild_id)

    async def _handle_accept(self, interaction: discord.Interaction, target_user_id: int) -> None:
        """Handle onboarding acceptance and assign member role."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This action must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(guild.id)
        if config.member_role_id is None:
            await interaction.response.send_message(
                "Setup incomplete: configure a verification member role with `/onboarding roles`.",
                ephemeral=True,
            )
            return

        role = guild.get_role(config.member_role_id)
        if role is None:
            await interaction.response.send_message(
                "Configured member role no longer exists. Please reconfigure `/onboarding roles`.",
                ephemeral=True,
            )
            return

        member = guild.get_member(target_user_id)
        if member is None:
            await interaction.response.send_message("Could not find that member in this server.", ephemeral=True)
            return

        bot_member = guild.me
        if bot_member is None and self.bot.user is not None:
            bot_member = guild.get_member(self.bot.user.id)

        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "I need **Manage Roles** permission to finish onboarding.",
                ephemeral=True,
            )
            return

        if bot_member.top_role <= role:
            await interaction.response.send_message(
                "I cannot assign that role because it is higher than or equal to my top role.",
                ephemeral=True,
            )
            return

        if role not in member.roles:
            await member.add_roles(role, reason="Completed onboarding rule acceptance")

        state = self._get_user_state(guild.id, target_user_id)
        state.status = "verified"
        state.completed_at_utc = utc_now()

        await interaction.response.send_message("✅ Verification complete. You now have member access.", ephemeral=True)
        await self._send_log_message(guild, config, f"✅ Verified {member.mention} ({member.id})")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Send setup checklist to first public channel when bot is added to a guild."""
        channel = self._first_public_text_channel(guild)
        if channel is None:
            self.log.warning("No public text channel available for setup message in guild %s", guild.id)
            return

        try:
            await channel.send(self._build_setup_message(guild), allowed_mentions=discord.AllowedMentions.none())
            self.log.info("Posted setup checklist for guild %s in channel %s", guild.id, channel.id)
        except discord.HTTPException as exc:
            self.log.warning("Failed to post setup checklist for guild %s: %s", guild.id, exc)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Start onboarding flow for newly joined members."""
        config = self._ensure_setup(member.guild.id)
        if not config.enabled:
            return

        if config.welcome_channel_id is None or config.member_role_id is None:
            self.log.info(
                "Skipping onboarding for member %s in guild %s due to incomplete setup.",
                member.id,
                member.guild.id,
            )
            return

        welcome_channel = member.guild.get_channel(config.welcome_channel_id)
        if not isinstance(welcome_channel, discord.TextChannel):
            self.log.info(
                "Configured welcome channel missing for guild %s; onboarding skipped for user %s.",
                member.guild.id,
                member.id,
            )
            return

        await self._mark_pending(member.guild.id, member.id)

        template = (
            config.onboarding_message_template
            or "Welcome {user}! Please review {rules} and click **Accept Rules** below to complete onboarding."
        )
        rendered = template.replace("{user}", member.mention).replace(
            "{rules}",
            config.rules_location or "the server rules",
        )

        view = VerifyView(
            target_user_id=member.id,
            on_accept=self._handle_accept,
            on_timeout_callback=partial(self._mark_timed_out, member.guild.id),
            timeout=1800,
        )

        sent = await welcome_channel.send(
            rendered,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            view=view,
        )
        view.message = sent

        if config.welcome_dm_enabled:
            try:
                await member.send(
                    f"Welcome to **{member.guild.name}**. Please complete onboarding in {welcome_channel.mention}."
                )
            except discord.HTTPException:
                self.log.info("Could not DM onboarding hint to member %s in guild %s", member.id, member.guild.id)

        await self._send_log_message(
            member.guild,
            config,
            f"🟡 Onboarding started for {member.mention} ({member.id})",
        )

    @onboarding.command(name="summary", description="Show current setup values and missing required items")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_summary(self, interaction: discord.Interaction) -> None:
        """Return a summary of setup state for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(interaction.guild.id)
        missing = self._missing_items(config)

        verification_member_role = (
            self._format_role_mentions(interaction.guild, [config.member_role_id])
            if config.member_role_id
            else "Not set"
        )
        missing_lines = [f"- {item}" for item in missing] if missing else ["- None"]

        lines = [
            "**Setup Summary**",
            f"Enabled: {'Yes' if config.enabled else 'No'}",
            f"Primary admin role(s): {self._format_role_mentions(interaction.guild, config.admin_role_ids)}",
            f"Moderator role(s): {self._format_role_mentions(interaction.guild, config.moderator_role_ids)}",
            f"Verification member role: {verification_member_role}",
            f"Log channel: {self._format_channel_mention(interaction.guild, config.log_channel_id)}",
            f"Announcement channel: {self._format_channel_mention(interaction.guild, config.announcement_channel_id)}",
            f"Welcome channel: {self._format_channel_mention(interaction.guild, config.welcome_channel_id)}",
            f"Welcome DMs enabled: {'Yes' if config.welcome_dm_enabled else 'No'}",
            f"Support/ticket channel: {self._format_channel_mention(interaction.guild, config.support_channel_id)}",
            f"Rules/verification flow: {config.rules_location or 'Not set'}",
            f"Acceptance method: {config.verification_acceptance}",
            "",
            "**Missing Required Items**",
            *missing_lines,
            "",
            "Storage is in-memory and resets on restart.",
        ]

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @onboarding.command(name="roles", description="Set trusted admin/mod roles and verification member role")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        admin_roles="Role mentions or IDs (space/comma separated)",
        moderator_roles="Role mentions or IDs (space/comma separated)",
        member_role="Role granted when onboarding is completed",
    )
    async def setup_roles(
        self,
        interaction: discord.Interaction,
        admin_roles: str | None = None,
        moderator_roles: str | None = None,
        member_role: discord.Role | None = None,
    ) -> None:
        """Update role-based setup settings for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(interaction.guild.id)

        if admin_roles is not None:
            config.admin_role_ids = self._parse_role_ids(admin_roles, interaction.guild)
        if moderator_roles is not None:
            config.moderator_role_ids = self._parse_role_ids(moderator_roles, interaction.guild)
        if member_role is not None:
            config.member_role_id = member_role.id

        await interaction.response.send_message("✅ Setup roles updated.", ephemeral=True)

    @onboarding.command(name="channels", description="Set channels used by logs, announcements, welcome, and support")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        log_channel="Channel for mod/automod/error logs",
        announcement_channel="Channel for server announcements",
        welcome_channel="Channel where onboarding welcome messages are posted",
        support_channel="Channel for support/ticket routing",
    )
    async def setup_channels(
        self,
        interaction: discord.Interaction,
        log_channel: discord.TextChannel | None = None,
        announcement_channel: discord.TextChannel | None = None,
        welcome_channel: discord.TextChannel | None = None,
        support_channel: discord.TextChannel | None = None,
    ) -> None:
        """Update channel-based setup settings for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(interaction.guild.id)

        if log_channel is not None:
            config.log_channel_id = log_channel.id
        if announcement_channel is not None:
            config.announcement_channel_id = announcement_channel.id
        if welcome_channel is not None:
            config.welcome_channel_id = welcome_channel.id
        if support_channel is not None:
            config.support_channel_id = support_channel.id

        await interaction.response.send_message("✅ Setup channels updated.", ephemeral=True)

    @onboarding.command(name="config", description="Set onboarding flow behavior")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        enabled="Enable or disable onboarding for this guild",
        welcome_dm_enabled="Send DM hint in addition to welcome channel message",
        rules_location="Where your rules/verification policy is documented (use 'clear' to unset)",
        message="Onboarding message template (use {user} and {rules}; use 'clear' to unset)",
    )
    async def setup_onboarding(
        self,
        interaction: discord.Interaction,
        enabled: bool | None = None,
        welcome_dm_enabled: bool | None = None,
        rules_location: str | None = None,
        message: str | None = None,
    ) -> None:
        """Update onboarding-specific setup settings for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(interaction.guild.id)

        if enabled is not None:
            config.enabled = enabled
        if welcome_dm_enabled is not None:
            config.welcome_dm_enabled = welcome_dm_enabled
        if rules_location is not None:
            config.rules_location = None if rules_location.strip().lower() == "clear" else rules_location.strip()
        if message is not None:
            config.onboarding_message_template = None if message.strip().lower() == "clear" else message

        await interaction.response.send_message("✅ Onboarding settings updated.", ephemeral=True)

    @onboarding.command(name="reset", description="Reset setup and onboarding state for this guild")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_reset(self, interaction: discord.Interaction) -> None:
        """Clear setup and user onboarding state for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        self._setup_store.pop(guild_id, None)

        prefix = f"{guild_id}:"
        for key in [state_key for state_key in self._user_state_store if state_key.startswith(prefix)]:
            self._user_state_store.pop(key, None)

        await interaction.response.send_message("✅ Setup and onboarding state reset for this guild.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Onboarding cog."""
    await bot.add_cog(Onboarding(bot))
