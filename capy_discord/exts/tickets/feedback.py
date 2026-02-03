"""Feedback submission cog."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.config import settings

from ._base import TicketBase
from ._schemas import FeedbackForm


class Feedback(TicketBase):
    """Cog for submitting general feedback."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Feedback cog."""
        command_config = {
            "cmd_name": "feedback",
            "cmd_name_verbose": "Feedback Report",
            "cmd_emoji": "📝",
            "description": "Provide general feedback",
            "request_channel_id": settings.ticket_feedback_channel_id,
        }
        color_config = {
            "unmarked_color": discord.Color.blue(),  # STATUS_INFO
            "marked_colors": {
                "Acknowledged": discord.Color.green(),  # STATUS_RESOLVED
                "Ignored": discord.Color.greyple(),  # STATUS_IGNORED
            },
        }
        super().__init__(
            bot,
            FeedbackForm,  # Pass Pydantic schema class
            {
                "✅": "Acknowledged",
                "❌": "Ignored",
                "🔄": "Unmarked",
            },
            command_config,
            color_config,
            " ✅ Acknowledge • ❌ Ignore • 🔄 Reset",
        )
        self.log = logging.getLogger(__name__)
        self.log.info("Feedback cog initialized")

    @app_commands.command(name="feedback", description="Provide general feedback")
    async def feedback(self, interaction: discord.Interaction) -> None:
        """Show feedback submission form."""
        try:
            await self._show_feedback_button(interaction)
        except Exception:
            self.log.exception(
                "Failed to process feedback command for user %s (ID: %s)",
                interaction.user,
                interaction.user.id,
            )

            error_msg = "❌ **Something went wrong!**\nPlease try again later."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Feedback cog."""
    await bot.add_cog(Feedback(bot))
