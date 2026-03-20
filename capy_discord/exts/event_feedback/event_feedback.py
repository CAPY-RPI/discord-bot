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
from capy_discord.services.dm import DirectMessenger, Policy
from capy_discord.ui.modal import BaseModal
from capy_discord.ui.views import BaseView

from ._schemas import EventFeedbackSchema

# Ratings at or above this threshold are considered positive and skip the follow-up question.
_POSITIVE_THRESHOLD = 6
_BAD_THRESHOLD = 3
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
        required=False,
    )

    def __init__(
        self, cog: "EventFeedback", rating: int, dm_message: discord.Message | None, view: "RatingView | None" = None
    ) -> None:
        """Initialize the ImprovementModal.

        Args:
            cog: The parent EventFeedback cog that owns the feedback store.
            rating: The numeric rating already submitted by the user.
            dm_message: The original DM message so the bot can update its buttons.
            view: The rating view to disable after submission.
        """
        super().__init__(title="Event Feedback - Tell Us More")
        self.cog = cog
        self.rating = rating
        self.dm_message = dm_message
        self.view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Persist feedback and acknowledge the user."""
        suggestion_value = self.suggestion.value.strip() or None
        await self.cog.save_feedback(interaction, self.rating, suggestion_value)

        # Mark view as responded and disable buttons on the original DM message.
        if self.view is not None:
            self.view.responded = True
            self.view.disable_all_items()

        if self.dm_message is not None:
            # Direct message edit - does not consume the modal's interaction response.
            with contextlib.suppress(discord.HTTPException):
                await self.dm_message.edit(view=None)


# ---------------------------------------------------------------------------
# Rating button + view
# ---------------------------------------------------------------------------


class RatingRangeButton(ui.Button["RatingView"]):
    """A button representing a range of rating values."""

    def __init__(self, label: str, style: discord.ButtonStyle, rating_range: tuple[int, int]) -> None:
        """Initialize the RatingRangeButton.

        Args:
            label: The text label for the button.
            style: The color/style of the button.
            rating_range: The range of ratings this button represents.
        """
        super().__init__(label=label, style=style)
        self.rating_range = rating_range

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle a button press and branch based on the chosen rating range."""
        view: RatingView = self.view  # type: ignore[assignment]

        if view.responded:
            await interaction.response.send_message("You've already submitted your rating - thanks!", ephemeral=True)
            return

        # Use the average of the range as the representative rating.
        average_rating = sum(self.rating_range) // 2

        if average_rating >= _POSITIVE_THRESHOLD:
            # Mark as responded and disable buttons immediately for positive ratings.
            view.responded = True
            view.disable_all_items()
            await interaction.response.edit_message(view=view)
            await self.cog.save_feedback(interaction, average_rating, None)
        else:
            # For negative ratings, defer disabling buttons until the modal is submitted.
            modal = ImprovementModal(cog=self.cog, rating=average_rating, dm_message=view.dm_message, view=view)
            await interaction.response.send_modal(modal)

    @property
    def cog(self) -> "EventFeedback":
        """Return the parent cog through the view reference."""
        view: RatingView = self.view  # type: ignore[assignment]
        return view.cog


class RatingView(BaseView):
    """View containing three rating range buttons sent in a DM."""

    def __init__(self, cog: "EventFeedback") -> None:
        """Initialize the RatingView with three rating range buttons."""
        super().__init__(timeout=600)  # 10-minute window for the user to respond
        self.cog = cog
        self.responded = False
        self.dm_message: discord.Message | None = None

        # Add three buttons for rating ranges.
        self.add_item(RatingRangeButton("1-3", discord.ButtonStyle.danger, (1, 3)))
        self.add_item(RatingRangeButton("4-6", discord.ButtonStyle.primary, (4, 6)))
        self.add_item(RatingRangeButton("7-10", discord.ButtonStyle.success, (7, 10)))


# ---------------------------------------------------------------------------
# Event Select Menu
# ---------------------------------------------------------------------------


class EventSelect(ui.Select["EventSelectView"]):
    """Select menu to choose which event to send feedback for."""

    def __init__(self) -> None:
        """Initialize the EventSelect with event options."""
        options = [
            discord.SelectOption(label="Event 1", value="event1"),
            discord.SelectOption(label="Event 2", value="event2"),
            discord.SelectOption(label="Event 3", value="event3"),
        ]
        super().__init__(placeholder="Choose an event...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle event selection."""
        view = self.view
        if view is None:
            await interaction.response.send_message("Unable to process event selection.", ephemeral=True)
            return
        selected_event = self.values[0]
        await view.cog._send_event_feedback(interaction, selected_event)


class EventSelectView(BaseView):
    """View containing the event select menu."""

    def __init__(self, cog: "EventFeedback") -> None:
        """Initialize the EventSelectView."""
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(EventSelect())


class ViewEventSelect(ui.Select["ViewEventSelectView"]):
    """Select menu to choose which event feedback to view."""

    def __init__(self) -> None:
        """Initialize the ViewEventSelect with event options."""
        options = [
            discord.SelectOption(label="Event 1", value="event1"),
            discord.SelectOption(label="Event 2", value="event2"),
            discord.SelectOption(label="Event 3", value="event3"),
        ]
        super().__init__(placeholder="Choose an event...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle event selection."""
        view = self.view
        if view is None:
            await interaction.response.send_message("Unable to process event selection.", ephemeral=True)
            return
        selected_event = self.values[0]
        await view.cog._view_event_feedback(interaction, selected_event)


class ViewEventSelectView(BaseView):
    """View containing the view event select menu."""

    def __init__(self, cog: "EventFeedback") -> None:
        """Initialize the ViewEventSelectView."""
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(ViewEventSelect())


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class EventFeedback(commands.Cog):
    """Collect post-event feedback from all guild members via DM."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the EventFeedback cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.dm_service = DirectMessenger()  # Initialize the DM service
        # [DB CALL]: Replace with actual DB storage in production.
        # feedback_data[guild_id][event_name][user_id] = EventFeedbackSchema(...)
        self.feedback_data: dict[int, dict[str, dict[int, EventFeedbackSchema]]] = {}
        # Tracks which guild/event a DM feedback response belongs to.
        self.pending_feedback_context_by_user: dict[int, tuple[int, str]] = {}
        # Snapshot display names at send-time for easier reporting.
        self.feedback_user_display_names: dict[int, dict[int, str]] = {}

    async def send_feedback_dm(self, guild: discord.Guild, member: discord.Member, content: str) -> None:
        """Send a feedback DM to a single guild member."""
        try:
            policy = Policy(max_recipients=1)  # Restrict to one recipient per call
            draft = await self.dm_service.compose_to_user(guild, user_id=member.id, content=content, policy=policy)
            result = await self.dm_service.send(guild, draft)

            if result.sent_count > 0:
                self.log.info("Successfully sent feedback DM to %s", member.display_name)
            else:
                self.log.warning("Failed to send feedback DM to %s", member.display_name)
        except Exception:
            self.log.exception("Error sending feedback DM to %s", member.display_name)

    async def collect_feedback(self, guild: discord.Guild, members: list[discord.Member], content: str) -> None:
        """Send feedback DMs to a list of guild members."""
        for member in members:
            await self.send_feedback_dm(guild, member, content)

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
        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M %p %Z")
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
                f"TEST MODE: user `{settings.test_user_id}` not found in this guild.", ephemeral=True
            )
            return None

        self.log.info("TEST MODE: restricting feedback DM to user %s", settings.test_user_id)
        return [test_member]

    def _normalize_event_name(self, event_name: str) -> str | None:
        """Normalize an event name from user input."""
        normalized = " ".join(event_name.split()).strip()
        return normalized or None

    @app_commands.command(
        name="event_feedback",
        description="Send a post-event feedback survey to all guild members via DM",
    )
    @app_commands.describe(event_name="Name of the event (for example: Spring Social)")
    async def event_feedback(self, interaction: discord.Interaction, event_name: str) -> None:
        """Send event feedback survey for a user-provided event name."""
        normalized_event_name = self._normalize_event_name(event_name)
        if normalized_event_name is None:
            await interaction.response.send_message("Please provide a valid event name.", ephemeral=True)
            return
        await self._send_event_feedback(interaction, normalized_event_name)

    async def _send_event_feedback(self, interaction: discord.Interaction, event_name: str) -> None:
        """Iterate over guild members and DM each one a rating view for the specified event."""
        # Defer so we can take our time sending potentially many DMs.
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("This command must be used inside a server.", ephemeral=True)
            return

        self._ensure_feedback_stores(guild.id, event_name)
        members = await self._resolve_target_members(interaction, guild)
        if members is None:
            return

        sent, failed = 0, 0
        for member in members:
            try:
                view = RatingView(cog=self)
                content = (
                    f"Hey {member.display_name}!\n\n"
                    f"We'd love your feedback on **{event_name}**.\n"
                    "Please rate it on a scale of **1-10** by clicking a button below:\n"
                )
                msg = await member.send(content=content, view=view)
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

        summary = f"Feedback survey for **{event_name}** sent to **{sent}** member(s)."
        if failed:
            summary += f"\nCould not reach **{failed}** member(s) (DMs may be disabled)."
        await interaction.followup.send(summary, ephemeral=True)

    def _rating_to_label(self, rating: int) -> str:
        """Convert numeric rating to a text label."""
        if rating <= _BAD_THRESHOLD:
            return "Bad"
        if rating <= _POSITIVE_THRESHOLD:
            return "Average"
        return "Good"

    @app_commands.command(
        name="view_feedback",
        description="View submitted event feedback for a specific event",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(event_name="Event name to view feedback for")
    async def view_feedback(self, interaction: discord.Interaction, event_name: str) -> None:
        """View collected feedback for a user-provided event name."""
        normalized_event_name = self._normalize_event_name(event_name)
        if normalized_event_name is None:
            await interaction.response.send_message("Please provide a valid event name.", ephemeral=True)
            return
        await self._view_event_feedback(interaction, normalized_event_name)

    @view_feedback.autocomplete("event_name")
    async def view_feedback_event_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Suggest event names that have stored feedback for this guild."""
        guild = interaction.guild
        if guild is None:
            return []

        event_names = sorted(self.feedback_data.get(guild.id, {}).keys())
        current_lower = current.lower().strip()
        if current_lower:
            event_names = [name for name in event_names if current_lower in name.lower()]

        return [app_commands.Choice(name=name, value=name) for name in event_names[:25]]

    async def _view_event_feedback(self, interaction: discord.Interaction, event_name: str) -> None:
        """Allow server owners/admins to view collected feedback for a specific event."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This command must be used inside a server.", ephemeral=True)
            return

        guild_feedback = self.feedback_data.get(guild.id, {})
        if not guild_feedback or event_name not in guild_feedback:
            await interaction.response.send_message(
                f"No feedback has been submitted for **{event_name}**.", ephemeral=True
            )
            return

        event_feedback = guild_feedback[event_name]
        name_snapshot = self.feedback_user_display_names.get(guild.id, {})
        lines: list[str] = []
        for user_id, feedback in event_feedback.items():
            member = guild.get_member(user_id)
            user_name = member.display_name if member is not None else name_snapshot.get(user_id, f"User {user_id}")
            suggestion = feedback.improvement_suggestion or "(No written feedback)"
            rating_label = self._rating_to_label(feedback.rating)
            lines.append(f"• **{user_name}**\n  Rating: **{rating_label}**\n  Feedback: {suggestion}")

        block_body = "\n\n".join(lines) if lines else "(No responses yet)"
        full_text = f"**Feedback for {event_name}**\n\n{block_body}"

        if len(full_text) <= _MAX_REPORT_CHARS:
            await interaction.response.send_message(full_text, ephemeral=True)
            return

        await interaction.response.send_message(f"Feedback for {event_name} (part 1):", ephemeral=True)
        current_chunk = ""
        part = 1
        for line in lines:
            entry = f"{line}\n\n"
            if len(current_chunk) + len(entry) > _MAX_REPORT_CHARS:
                await interaction.followup.send(f"Part {part}:\n{current_chunk}", ephemeral=True)
                part += 1
                current_chunk = entry
            else:
                current_chunk += entry
        if current_chunk:
            await interaction.followup.send(f"Part {part}:\n{current_chunk}", ephemeral=True)

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
            message = "Response received, but I couldn't link it to a server context. Please try again."
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

        message = "Response recorded. Thank you for your feedback."

        if not interaction.response.is_done():
            await interaction.response.send_message(message)
        else:
            await interaction.followup.send(message)


async def setup(bot: commands.Bot) -> None:
    """Set up the EventFeedback cog."""
    await bot.add_cog(EventFeedback(bot))
