"""Onboarding configuration and verification flow.

This extension provides:
- Guild bootstrap checklist on bot invite.
- In-memory onboarding configuration via /onboarding commands.
- Member onboarding with rule acknowledgement and role assignment.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
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


class Onboarding(commands.GroupCog, group_name="onboarding", group_description="Configure member onboarding"):
    """Cog that manages guild onboarding and member verification."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize in-memory stores for onboarding and user state."""
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

        grace_tasks: dict[str, asyncio.Task[None]] | None = getattr(bot, "onboarding_grace_tasks", None)
        if grace_tasks is None:
            grace_tasks = {}
            setattr(bot, "onboarding_grace_tasks", grace_tasks)  # noqa: B010

        self._setup_store = setup_store
        self._user_state_store = user_state_store
        self._grace_tasks = grace_tasks

    def _state_key(self, guild_id: int, user_id: int) -> str:
        """Build deterministic key for user onboarding state."""
        return f"{guild_id}:{user_id}"

    def _ensure_setup(self, guild_id: int) -> GuildSetupConfig:
        """Get or create onboarding configuration for a guild."""
        if guild_id not in self._setup_store:
            self._setup_store[guild_id] = GuildSetupConfig()
        return self._setup_store[guild_id]

    def _get_user_state(self, guild_id: int, user_id: int) -> UserOnboardingState:
        """Get or create a user's onboarding lifecycle state."""
        key = self._state_key(guild_id, user_id)
        if key not in self._user_state_store:
            self._user_state_store[key] = UserOnboardingState()
        return self._user_state_store[key]

    def _cancel_grace_task(self, guild_id: int, user_id: int) -> None:
        """Cancel any existing grace-period check for a user."""
        key = self._state_key(guild_id, user_id)
        task = self._grace_tasks.pop(key, None)
        if task is not None and not task.done():
            task.cancel()

    def _schedule_grace_period_check(self, guild_id: int, user_id: int, attempt_id: int) -> None:
        """Start the grace-period enforcement task for a member."""
        self._cancel_grace_task(guild_id, user_id)
        task = asyncio.create_task(self._enforce_grace_period(guild_id, user_id, attempt_id))
        self._grace_tasks[self._state_key(guild_id, user_id)] = task

    def _get_bot_member(self, guild: discord.Guild) -> discord.Member | None:
        """Return the bot's guild member instance."""
        bot_member = guild.me
        if bot_member is None and self.bot.user is not None:
            bot_member = guild.get_member(self.bot.user.id)
        return bot_member

    def _first_public_text_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Return first public text channel where bot can post."""
        bot_member = self._get_bot_member(guild)
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
        """Return required onboarding items that are still missing."""
        missing: list[str] = []
        if config.log_channel_id is None:
            missing.append("Log channel")
        if config.welcome_channel_id is None:
            missing.append("Welcome channel")
        if not config.rules_location:
            missing.append("Rules/verification flow")
        if config.member_role_id is None:
            missing.append("Member role for verified users")
        return missing

    def _build_onboarding_message(self, guild: discord.Guild) -> str:
        """Build a guild-specific onboarding checklist message."""
        config = self._ensure_setup(guild.id)
        missing = self._missing_items(config)

        status_lines = [
            f"- Log channel: {self._format_channel_mention(guild, config.log_channel_id)}",
            f"- Onboarding event logging: {'Yes' if config.log_events else 'No'}",
            f"- Welcome channel: {self._format_channel_mention(guild, config.welcome_channel_id)}",
            f"- Welcome DMs enabled: {'Yes' if config.welcome_dm_enabled else 'No'}",
            f"- Auto-remove unverified members: {'Yes' if config.auto_kick_unverified else 'No'}",
            f"- Grace period: {config.grace_period_hours} hour(s)",
            f"- Rules/verification flow: {config.rules_location or 'Not set'}",
            (
                "- Verification member role: "
                f"{self._format_role_mentions(guild, [config.member_role_id]) if config.member_role_id else 'Not set'}"
            ),
        ]

        missing_text = "\n".join(f"- {item}" for item in missing) if missing else "- None"

        return (
            "Thanks for inviting CAPY.\n\n"
            "Run these commands to configure onboarding:\n"
            "- `/onboarding roles`\n"
            "- `/onboarding channels`\n"
            "- `/onboarding config`\n"
            "- `/onboarding summary`\n\n"
            "**Current Onboarding Status**\n"
            f"{'\n'.join(status_lines)}\n\n"
            "**Missing Required Items**\n"
            f"{missing_text}\n\n"
            "Data storage is currently in-memory and resets on bot restart."
        )

    async def _send_log_message(self, guild: discord.Guild, config: GuildSetupConfig, message: str) -> None:
        """Send a best-effort onboarding event log message to the configured log channel."""
        if not config.log_events or config.log_channel_id is None:
            return

        channel = guild.get_channel(config.log_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            self.log.warning("Failed to send onboarding log message in guild %s: %s", guild.id, exc)

    async def _mark_pending(self, guild_id: int, user_id: int) -> int:
        """Mark user state as pending and increment attempt count."""
        state = self._get_user_state(guild_id, user_id)
        state.status = "pending"
        state.started_at_utc = utc_now()
        state.completed_at_utc = None
        state.attempts += 1
        return state.attempts

    def _reset_onboarding_state(self, guild_id: int, user_id: int, *, attempt_id: int | None = None) -> bool:
        """Reset a pending onboarding attempt back to a clean retriable state."""
        state = self._get_user_state(guild_id, user_id)
        if state.status != "pending":
            return False
        if attempt_id is not None and state.attempts != attempt_id:
            return False

        state.status = "new"
        state.started_at_utc = None
        state.completed_at_utc = None
        return True

    def _render_onboarding_message(
        self,
        member: discord.Member,
        config: GuildSetupConfig,
        *,
        is_retry: bool = False,
    ) -> str:
        """Render the onboarding prompt content for a member."""
        template = (
            config.onboarding_message_template
            or "Welcome {user}! Please review {rules} and click **Accept Rules** below to complete onboarding."
        )
        rendered = template.replace("{user}", member.mention).replace(
            "{rules}",
            config.rules_location or "the server rules",
        )
        if not is_retry:
            return rendered

        return (
            f"{member.mention} your previous verification button timed out. "
            "Here is a fresh one so you can finish onboarding.\n\n"
            f"{rendered}"
        )

    async def _send_verification_prompt(self, member: discord.Member, *, is_retry: bool = False) -> bool:
        """Post a verification prompt and start the matching grace-period task."""
        config = self._ensure_setup(member.guild.id)
        if not config.enabled or config.welcome_channel_id is None or config.member_role_id is None:
            return False

        welcome_channel = member.guild.get_channel(config.welcome_channel_id)
        if not isinstance(welcome_channel, discord.TextChannel):
            return False

        attempt_id = await self._mark_pending(member.guild.id, member.id)
        view = VerifyView(
            attempt_id=attempt_id,
            target_user_id=member.id,
            on_accept=self._handle_accept,
            on_timeout_callback=partial(self._handle_verification_timeout, member.guild.id, attempt_id),
            timeout=1800,
        )

        sent = await welcome_channel.send(
            self._render_onboarding_message(member, config, is_retry=is_retry),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            view=view,
        )
        view.message = sent
        self._schedule_grace_period_check(member.guild.id, member.id, attempt_id)
        return True

    async def _handle_verification_timeout(self, guild_id: int, attempt_id: int, user_id: int) -> None:
        """Reset stale timeout state and automatically repost a fresh verification prompt."""
        if not self._reset_onboarding_state(guild_id, user_id, attempt_id=attempt_id):
            return

        self._cancel_grace_task(guild_id, user_id)
        self.log.info("Onboarding timed out for user %s in guild %s", user_id, guild_id)

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return

        config = self._ensure_setup(guild_id)
        member = guild.get_member(user_id)
        member_text = f"{member.mention} ({member.id})" if member is not None else f"user {user_id}"
        await self._send_log_message(guild, config, f"🟠 Onboarding timed out for {member_text}")

        if member is None:
            return

        reposted = await self._send_verification_prompt(member, is_retry=True)
        if reposted:
            await self._send_log_message(
                guild,
                config,
                f"🔁 Reposted verification prompt for {member.mention} ({member.id}) after timeout.",
            )

    async def _enforce_grace_period(self, guild_id: int, user_id: int, attempt_id: int) -> None:
        """Remove unverified members after the configured grace period."""
        try:
            config = self._ensure_setup(guild_id)
            await asyncio.sleep(config.grace_period_hours * 3600)

            config = self._ensure_setup(guild_id)
            state = self._get_user_state(guild_id, user_id)
            if (
                not config.auto_kick_unverified
                or state.status == "verified"
                or state.started_at_utc is None
                or state.attempts != attempt_id
            ):
                return

            deadline = state.started_at_utc + timedelta(hours=config.grace_period_hours)
            if utc_now() < deadline:
                return

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return

            member = guild.get_member(user_id)
            if member is None:
                return

            bot_member = self._get_bot_member(guild)
            if bot_member is None or not bot_member.guild_permissions.kick_members:
                self.log.warning(
                    "Missing Kick Members permission for overdue onboarding for user %s in guild %s",
                    user_id,
                    guild_id,
                )
                await self._send_log_message(
                    guild,
                    config,
                    (
                        f"⚠️ Could not remove {member.mention} ({member.id}) after onboarding grace period: "
                        "missing Kick Members."
                    ),
                )
                return

            if bot_member.top_role <= member.top_role:
                self.log.warning("Cannot kick member %s in guild %s due to role hierarchy", user_id, guild_id)
                await self._send_log_message(
                    guild,
                    config,
                    (
                        f"⚠️ Could not remove {member.mention} ({member.id}) after onboarding grace period "
                        "due to role hierarchy."
                    ),
                )
                return

            await member.kick(reason="Did not complete onboarding within the configured grace period")
            state.status = "new"
            await self._send_log_message(
                guild,
                config,
                (
                    f"🔴 Removed {member.mention} ({member.id}) for not completing onboarding within "
                    f"{config.grace_period_hours} hour(s)."
                ),
            )
        except asyncio.CancelledError:
            raise
        except discord.HTTPException as exc:
            self.log.warning("Failed to remove overdue onboarding member %s in guild %s: %s", user_id, guild_id, exc)
        finally:
            key = self._state_key(guild_id, user_id)
            if self._grace_tasks.get(key) is asyncio.current_task():
                self._grace_tasks.pop(key, None)

    def _resolve_accept_context(
        self,
        guild: discord.Guild | None,
        target_user_id: int,
        attempt_id: int,
    ) -> tuple[str | None, GuildSetupConfig | None, discord.Member | None, discord.Role | None]:
        """Validate an onboarding acceptance attempt and return the resolved entities."""
        failure_message: str | None = None
        config: GuildSetupConfig | None = None
        member: discord.Member | None = None
        role: discord.Role | None = None

        if guild is None:
            failure_message = "This action must be used in a server."
        else:
            state = self._get_user_state(guild.id, target_user_id)
            if state.status != "pending" or state.attempts != attempt_id:
                failure_message = "This verification prompt has expired. Use the newest button in the welcome channel."
            else:
                config = self._ensure_setup(guild.id)
                if config.member_role_id is None:
                    failure_message = (
                        "Onboarding is incomplete: configure a verification member role with `/onboarding roles`."
                    )
                else:
                    role = guild.get_role(config.member_role_id)
                    if role is None:
                        failure_message = (
                            "Configured member role no longer exists. Please reconfigure `/onboarding roles`."
                        )
                    else:
                        member = guild.get_member(target_user_id)
                        if member is None:
                            failure_message = "Could not find that member in this server."
                        else:
                            bot_member = self._get_bot_member(guild)
                            if bot_member is None or not bot_member.guild_permissions.manage_roles:
                                failure_message = "I need **Manage Roles** permission to finish onboarding."
                            elif bot_member.top_role <= role:
                                failure_message = (
                                    "I cannot assign that role because it is higher than or equal to my top role."
                                )

        return failure_message, config, member, role

    async def _handle_accept(self, interaction: discord.Interaction, target_user_id: int, attempt_id: int) -> bool:
        """Handle onboarding acceptance and assign member role."""
        failure_message, config, member, role = self._resolve_accept_context(
            interaction.guild,
            target_user_id,
            attempt_id,
        )

        if failure_message is not None:
            await interaction.response.send_message(failure_message, ephemeral=True)
            return False

        guild = interaction.guild
        if guild is None or config is None or member is None or role is None:
            await interaction.response.send_message("This verification prompt is no longer valid.", ephemeral=True)
            return False

        if role not in member.roles:
            await member.add_roles(role, reason="Completed onboarding rule acceptance")

        state = self._get_user_state(guild.id, target_user_id)
        state.status = "verified"
        state.completed_at_utc = utc_now()
        self._cancel_grace_task(guild.id, target_user_id)

        await interaction.response.send_message("✅ Verification complete. You now have member access.", ephemeral=True)
        await self._send_log_message(guild, config, f"✅ Verified {member.mention} ({member.id})")
        return True

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Send onboarding checklist to first public channel when bot is added to a guild."""
        channel = self._first_public_text_channel(guild)
        if channel is None:
            self.log.warning("No public text channel available for onboarding message in guild %s", guild.id)
            return

        try:
            await channel.send(self._build_onboarding_message(guild), allowed_mentions=discord.AllowedMentions.none())
            self.log.info("Posted onboarding checklist for guild %s in channel %s", guild.id, channel.id)
        except discord.HTTPException as exc:
            self.log.warning("Failed to post onboarding checklist for guild %s: %s", guild.id, exc)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Start onboarding flow for newly joined members."""
        config = self._ensure_setup(member.guild.id)
        if not config.enabled:
            return

        if config.welcome_channel_id is None or config.member_role_id is None:
            self.log.info(
                "Skipping onboarding for member %s in guild %s due to incomplete onboarding config.",
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

        posted = await self._send_verification_prompt(member)
        if not posted:
            self.log.info(
                "Could not post onboarding prompt for member %s in guild %s after initial validation.",
                member.id,
                member.guild.id,
            )
            return

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

    @app_commands.command(name="summary", description="Show current onboarding values and missing required items")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def onboarding_summary(self, interaction: discord.Interaction) -> None:
        """Return a summary of onboarding state for this guild."""
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
            "**Onboarding Summary**",
            f"Enabled: {'Yes' if config.enabled else 'No'}",
            f"Verification member role: {verification_member_role}",
            f"Log channel: {self._format_channel_mention(interaction.guild, config.log_channel_id)}",
            f"Onboarding event logging: {'Yes' if config.log_events else 'No'}",
            f"Welcome channel: {self._format_channel_mention(interaction.guild, config.welcome_channel_id)}",
            f"Welcome DMs enabled: {'Yes' if config.welcome_dm_enabled else 'No'}",
            f"Auto-remove unverified members: {'Yes' if config.auto_kick_unverified else 'No'}",
            f"Grace period: {config.grace_period_hours} hour(s)",
            f"Rules/verification flow: {config.rules_location or 'Not set'}",
            f"Acceptance method: {config.verification_acceptance}",
            "",
            "**Missing Required Items**",
            *missing_lines,
            "",
            "Storage is in-memory and resets on restart.",
        ]

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="roles", description="Set the verification member role")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        member_role="Role granted when onboarding is completed",
    )
    async def onboarding_roles(
        self,
        interaction: discord.Interaction,
        member_role: discord.Role | None = None,
    ) -> None:
        """Update role-based onboarding settings for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(interaction.guild.id)

        if member_role is not None:
            config.member_role_id = member_role.id

        await interaction.response.send_message("✅ Onboarding roles updated.", ephemeral=True)

    @app_commands.command(name="channels", description="Set channels used by onboarding logs and welcome prompts")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        log_channel="Channel for onboarding lifecycle logs",
        welcome_channel="Channel where onboarding welcome messages are posted",
    )
    async def onboarding_channels(
        self,
        interaction: discord.Interaction,
        log_channel: discord.TextChannel | None = None,
        welcome_channel: discord.TextChannel | None = None,
    ) -> None:
        """Update channel-based onboarding settings for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(interaction.guild.id)

        if log_channel is not None:
            config.log_channel_id = log_channel.id
        if welcome_channel is not None:
            config.welcome_channel_id = welcome_channel.id

        await interaction.response.send_message("✅ Onboarding channels updated.", ephemeral=True)

    @app_commands.command(name="config", description="Set onboarding flow behavior")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        enabled="Enable or disable onboarding for this guild",
        welcome_dm_enabled="Send DM hint in addition to welcome channel message",
        auto_kick_unverified="Remove users who do not complete onboarding within the grace period",
        grace_period_hours="Hours to wait before removing unverified members",
        log_events="Write onboarding start, completion, timeout, and removal events to the log channel",
        rules_location="Where your rules/verification policy is documented (use 'clear' to unset)",
        message="Onboarding message template (use {user} and {rules}; use 'clear' to unset)",
    )
    async def onboarding_config(  # noqa: PLR0913
        self,
        interaction: discord.Interaction,
        enabled: bool | None = None,
        welcome_dm_enabled: bool | None = None,
        auto_kick_unverified: bool | None = None,
        grace_period_hours: app_commands.Range[int, 1, 168] | None = None,
        log_events: bool | None = None,
        rules_location: str | None = None,
        message: str | None = None,
    ) -> None:
        """Update onboarding-specific settings for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        config = self._ensure_setup(interaction.guild.id)

        if enabled is not None:
            config.enabled = enabled
        if welcome_dm_enabled is not None:
            config.welcome_dm_enabled = welcome_dm_enabled
        if auto_kick_unverified is not None:
            config.auto_kick_unverified = auto_kick_unverified
        if grace_period_hours is not None:
            config.grace_period_hours = grace_period_hours
        if log_events is not None:
            config.log_events = log_events
        if rules_location is not None:
            config.rules_location = None if rules_location.strip().lower() == "clear" else rules_location.strip()
        if message is not None:
            config.onboarding_message_template = None if message.strip().lower() == "clear" else message

        await interaction.response.send_message("✅ Onboarding settings updated.", ephemeral=True)

    @app_commands.command(name="reset", description="Reset onboarding config and member state for this guild")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def onboarding_reset(self, interaction: discord.Interaction) -> None:
        """Clear onboarding config and user state for this guild."""
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        self._setup_store.pop(guild_id, None)

        prefix = f"{guild_id}:"
        for key in [task_key for task_key in self._grace_tasks if task_key.startswith(prefix)]:
            task = self._grace_tasks.pop(key)
            if not task.done():
                task.cancel()
        for key in [state_key for state_key in self._user_state_store if state_key.startswith(prefix)]:
            self._user_state_store.pop(key, None)

        await interaction.response.send_message("✅ Onboarding state reset for this guild.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Onboarding cog."""
    await bot.add_cog(Onboarding(bot))
