"""Event feedback extension.

Sends a DM rating survey (1-10) to every guild member after an event.
Members who rate below 6 are prompted for improvement suggestions.
All responses are stored in-memory (see [DB CALL] comments for future persistence).
"""

import contextlib
import logging

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.ui.modal import BaseModal
from capy_discord.ui.views import BaseView

from ._schemas import EventFeedbackSchema

# Ratings at or above this threshold are considered positive and skip the follow-up question.
_POSITIVE_THRESHOLD = 6


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
        self.feedback_data: dict[int, EventFeedbackSchema] = {}

    # ------------------------------------------------------------------
    # Slash command
    # ------------------------------------------------------------------

    @app_commands.command(
        name="event_feedback",
        description="Send a post-event feedback survey to all guild members via DM",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def event_feedback(self, interaction: discord.Interaction) -> None:
        """Iterate over guild members and DM each one a rating view."""
        # Defer so we can take our time sending potentially many DMs.
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("❌ This command must be used inside a server.", ephemeral=True)
            return

        # For now, all non-bot guild members represent event attendees.
        # [ATTENDANCE CALL]: Replace guild.members with the actual attendee list once implemented.
        members = [m for m in guild.members if not m.bot]

        sent, failed = 0, 0
        for member in members:
            try:
                view = RatingView(cog=self)
                msg = await member.send(
                    content=(
                        f"Hey {member.display_name}! 👋\n\n"
                        "We'd love your feedback on the recent event.\n"
                        "Please rate it on a scale of **1-10** by clicking a button below:\n"
                        "*(🟢 6-10 = Good  |  🔴 1-5 = Could be better)*"
                    ),
                    view=view,
                )
                # Store the message reference so the view can update it later.
                view.dm_message = msg
                sent += 1
            except discord.Forbidden:
                self.log.warning("Could not DM member %s (DMs disabled or bot blocked)", member.id)
                failed += 1
            except discord.HTTPException:
                self.log.exception("Unexpected error DMing member %s", member.id)
                failed += 1

        self.log.info(
            "event_feedback invoked by %s in guild %s: sent=%s failed=%s",
            interaction.user.id,
            guild.id,
            sent,
            failed,
        )

        summary = f"✅ Feedback survey sent to **{sent}** member(s)."
        if failed:
            summary += f"\n⚠️ Could not reach **{failed}** member(s) (DMs may be disabled)."
        await interaction.followup.send(summary, ephemeral=True)

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

        # [DB CALL]: Upsert a feedback record keyed by user_id.
        self.feedback_data[user_id] = EventFeedbackSchema(rating=rating, improvement_suggestion=suggestion)

        self.log.info(
            "Feedback saved - user=%s rating=%s suggestion_provided=%s",
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
