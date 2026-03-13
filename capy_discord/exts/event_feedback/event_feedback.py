"""Event feedback extension.

Sends a DM rating survey (1-10) to every guild member after an event.
Members who rate below 6 are prompted for improvement suggestions.
All responses are stored in-memory (see [DB CALL] comments for future persistence).
"""

import contextlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.config import settings
from capy_discord.ui.modal import BaseModal
from capy_discord.ui.views import BaseView

from ._schemas import EventFeedbackSchema

# Ratings at or above this threshold are considered positive and skip the follow-up question.
_POSITIVE_THRESHOLD = 6
_MAX_REPORT_CHARS = 1900


# ---------------------------------------------------------------------------
# Modal - shown only when the user's rating is below the threshold
# ---------------------------------------------------------------------------


class ImprovementModal(BaseModal):
    """Modal that collects a free-text improvement suggestion."""

    suggestion: ui.TextInput = ui.TextInput(
        label="How could we make the event better?",
        placeholder="Share your thoughts with us…",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    def __init__(self, cog: "EventFeedback", rating: int, dm_message: discord.Message | None) -> None:
        """Initialize the ImprovementModal.

        Args:
            cog: The parent EventFeedback cog that owns the feedback store.
            rating: The numeric rating already submitted by the user.
            dm_message: The original DM message so the bot can update its buttons.
        """
        super().__init__(title="Event Feedback - Tell Us More")
        self.cog = cog
        self.rating = rating
        self.dm_message = dm_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Persist feedback and acknowledge the user."""
        await self.cog.save_feedback(interaction, self.rating, self.suggestion.value)

        # Disable buttons on the original DM message now that the flow is complete.
        if self.dm_message is not None:
            # Direct message edit - does not consume the modal's interaction response.
            with contextlib.suppress(discord.HTTPException):
                await self.dm_message.edit(view=None)


# ---------------------------------------------------------------------------
# Rating button + view
# ---------------------------------------------------------------------------


class RatingButton(ui.Button["RatingView"]):
    """A single numbered button representing one rating value."""

    def __init__(self, rating: int) -> None:
        """Initialize the RatingButton."""
        style = discord.ButtonStyle.success if rating >= _POSITIVE_THRESHOLD else discord.ButtonStyle.danger
        super().__init__(label=str(rating), style=style, row=0 if rating < _POSITIVE_THRESHOLD else 1)
        self.rating = rating

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle a button press and branch based on the chosen rating."""
        view: RatingView = self.view  # type: ignore[assignment]

        # Guard against double-clicks while the modal/response is in flight.
        if view.responded:
            await interaction.response.send_message("You've already submitted your rating - thanks!", ephemeral=True)
            return

        view.responded = True
        view.disable_all_items()

        if self.rating >= _POSITIVE_THRESHOLD:
            # Edit the DM in-place to show disabled buttons, then send a follow-up.
            await interaction.response.edit_message(view=view)
            await self.cog.save_feedback(interaction, self.rating, None)
        else:
            # Open the improvement modal.  The modal's own on_submit will:
            #   1. persist the data, and
            #   2. edit the original message to remove the buttons.
            modal = ImprovementModal(cog=self.cog, rating=self.rating, dm_message=view.dm_message)
            await interaction.response.send_modal(modal)

    @property
    def cog(self) -> "EventFeedback":
        """Return the parent cog through the view reference."""
        view: RatingView = self.view  # type: ignore[assignment]
        return view.cog


class RatingView(BaseView):
    """View containing ten rating buttons (1-10) sent in a DM."""

    def __init__(self, cog: "EventFeedback") -> None:
        """Initialize the RatingView with ten rating buttons."""
        super().__init__(timeout=600)  # 10-minute window for the user to respond
        self.cog = cog
        self.responded = False
        # Separate from BaseView.message (InteractionMessage) - DMs return discord.Message.
        self.dm_message: discord.Message | None = None

        for i in range(1, 11):
            self.add_item(RatingButton(i))


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class EventFeedback(commands.Cog):
    """Collect post-event feedback from all guild members via DM."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the EventFeedback cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        # [DB CALL]: Replace with actual DB storage in production.
        # feedback_data[guild_id][event_name][user_id] = EventFeedbackSchema(...)
        self.feedback_data: dict[int, dict[str, dict[int, EventFeedbackSchema]]] = {}
        # Tracks which guild/event a DM feedback response belongs to.
        self.pending_feedback_context_by_user: dict[int, tuple[int, str]] = {}
        # Snapshot display names at send-time for easier reporting.
        self.feedback_user_display_names: dict[int, dict[int, str]] = {}

    def _ensure_feedback_stores(self, guild_id: int, event_name: str) -> None:
        """Initialize nested in-memory stores for guild/event feedback."""
        if guild_id not in self.feedback_data:
            self.feedback_data[guild_id] = {}
        if event_name not in self.feedback_data[guild_id]:
            self.feedback_data[guild_id][event_name] = {}
        if guild_id not in self.feedback_user_display_names:
            self.feedback_user_display_names[guild_id] = {}

    def _default_event_name(self) -> str:
        """Build a default event label for feedback batches."""
        timestamp = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC")
        return f"Event {timestamp}"

    async def _resolve_target_members(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
    ) -> list[discord.Member] | None:
        """Resolve which members should receive feedback DMs.

        Returns:
            A member list, or None if resolution fails and a user-facing message was sent.
        """
        # For now, all non-bot guild members represent event attendees.
        # [ATTENDANCE CALL]: Replace guild.members with the actual attendee list once implemented.
        if settings.test_user_id is None:
            return [m for m in guild.members if not m.bot]

        # TEST MODE: only DM the configured test user.
        test_member = guild.get_member(settings.test_user_id)
        if test_member is None:
            await interaction.followup.send(
                f"⚠️ TEST MODE: user `{settings.test_user_id}` not found in this guild.", ephemeral=True
            )
            return None

        self.log.info("TEST MODE: restricting feedback DM to user %s", settings.test_user_id)
        return [test_member]

    # ------------------------------------------------------------------
    # Slash command
    # ------------------------------------------------------------------

    @app_commands.command(
        name="event_feedback",
        description="Send a post-event feedback survey to all guild members via DM",
    )
    # TODO: re-enable before production - hides command from non-admins in Discord UI
    # @app_commands.default_permissions(manage_guild=True)
    async def event_feedback(self, interaction: discord.Interaction) -> None:
        """Iterate over guild members and DM each one a rating view."""
        # Defer so we can take our time sending potentially many DMs.
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("❌ This command must be used inside a server.", ephemeral=True)
            return

        event_name = self._default_event_name()

        self._ensure_feedback_stores(guild.id, event_name)
        members = await self._resolve_target_members(interaction, guild)
        if members is None:
            return

        sent, failed = 0, 0
        for member in members:
            try:
                view = RatingView(cog=self)
                msg = await member.send(
                    content=(
                        f"Hey {member.display_name}! 👋\n\n"
                        f"We'd love your feedback on **{event_name}**.\n"
                        "Please rate it on a scale of **1-10** by clicking a button below:\n"
                        "*(🟢 6-10 = Good  |  🔴 1-5 = Could be better)*"
                    ),
                    view=view,
                )
                # Store the message reference so the view can update it later.
                view.dm_message = msg
                self.pending_feedback_context_by_user[member.id] = (guild.id, event_name)
                self.feedback_user_display_names[guild.id][member.id] = member.display_name
                sent += 1
            except discord.Forbidden:
                self.log.warning("Could not DM member %s (DMs disabled or bot blocked)", member.id)
                failed += 1
            except discord.HTTPException:
                self.log.exception("Unexpected error DMing member %s", member.id)
                failed += 1

        self.log.info(
            "event_feedback invoked by %s in guild %s for event '%s': sent=%s failed=%s",
            interaction.user.id,
            guild.id,
            event_name,
            sent,
            failed,
        )

        summary = f"✅ Feedback survey for **{event_name}** sent to **{sent}** member(s)."
        if failed:
            summary += f"\n⚠️ Could not reach **{failed}** member(s) (DMs may be disabled)."
        await interaction.followup.send(summary, ephemeral=True)

    @app_commands.command(
        name="view_feedback",
        description="View submitted event feedback for this server",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def view_feedback(self, interaction: discord.Interaction) -> None:
        """Allow server owners/admins to view collected feedback for their guild."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ This command must be used inside a server.", ephemeral=True)
            return

        guild_feedback = self.feedback_data.get(guild.id, {})
        if not guild_feedback:
            await interaction.response.send_message("No feedback has been submitted yet.", ephemeral=True)
            return

        name_snapshot = self.feedback_user_display_names.get(guild.id, {})
        blocks: list[str] = []
        for event_name, event_feedback in guild_feedback.items():
            lines: list[str] = []
            for user_id, feedback in event_feedback.items():
                member = guild.get_member(user_id)
                user_name = member.display_name if member is not None else name_snapshot.get(user_id, f"User {user_id}")
                suggestion = feedback.improvement_suggestion or "(No written feedback)"
                lines.append(f"• **{user_name}**\n  Rating: **{feedback.rating}/10**\n  Feedback: {suggestion}")

            block_body = "\n\n".join(lines) if lines else "(No responses yet)"
            blocks.append(f"**Feedback for {event_name}**\n\n{block_body}")

        full_text = "\n\n---\n\n".join(blocks)
        if len(full_text) <= _MAX_REPORT_CHARS:
            await interaction.response.send_message(full_text, ephemeral=True)
            return

        # Fallback: split large reports into multiple ephemeral follow-ups.
        await interaction.response.send_message("Feedback report (part 1):", ephemeral=True)
        current_chunk = ""
        part = 1
        for block in blocks:
            entry = f"{block}\n\n"
            if len(current_chunk) + len(entry) > _MAX_REPORT_CHARS:
                await interaction.followup.send(f"Part {part}:\n{current_chunk}", ephemeral=True)
                part += 1
                current_chunk = entry
            else:
                current_chunk += entry
        if current_chunk:
            await interaction.followup.send(f"Part {part}:\n{current_chunk}", ephemeral=True)

    # ------------------------------------------------------------------
    # Shared persistence helper
    # ------------------------------------------------------------------

    async def save_feedback(
        self,
        interaction: discord.Interaction,
        rating: int,
        suggestion: str | None,
    ) -> None:
        """Persist a user's feedback entry and acknowledge them.

        Args:
            interaction: The interaction to respond to.
            rating: The numeric rating the user chose.
            suggestion: Optional improvement text (only present when rating < threshold).
        """
        user_id = interaction.user.id
        context = self.pending_feedback_context_by_user.get(user_id)

        if context is None:
            self.log.warning("Unable to determine guild context for feedback from user %s", user_id)
            message = "⚠️ Response received, but I couldn't link it to a server context. Please try again."
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
            return

        guild_id, event_name = context

        if guild_id not in self.feedback_data:
            self.feedback_data[guild_id] = {}
        if event_name not in self.feedback_data[guild_id]:
            self.feedback_data[guild_id][event_name] = {}

        # [DB CALL]: Upsert a feedback record keyed by (guild_id, event_name, user_id).
        self.feedback_data[guild_id][event_name][user_id] = EventFeedbackSchema(
            rating=rating,
            improvement_suggestion=suggestion,
        )

        self.log.info(
            "Feedback saved - guild=%s event='%s' user=%s rating=%s suggestion_provided=%s",
            guild_id,
            event_name,
            user_id,
            rating,
            suggestion is not None,
        )

        message = "✅ Response recorded! Thank you for your feedback! 🎉"

        if not interaction.response.is_done():
            await interaction.response.send_message(message)
        else:
            await interaction.followup.send(message)


async def setup(bot: commands.Bot) -> None:
    """Set up the EventFeedback cog."""
    await bot.add_cog(EventFeedback(bot))
