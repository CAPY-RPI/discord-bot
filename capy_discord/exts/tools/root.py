"""Minimal slash command for testing `/root` actions."""

import logging

import discord
from discord import app_commands
from discord.ext import commands


class Root(commands.Cog):
    """Cog for root test actions."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Root cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Root cog initialized")

    @app_commands.command(name="root", description="Root test command")
    @app_commands.describe(
        action="The root test action to perform",
        channel_type="Channel setting type when using action:channel",
        channel="Channel to select when using action:channel",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="channel", value="channel"),
        ],
        channel_type=[
            app_commands.Choice(name="feature", value="feedback"),
            app_commands.Choice(name="error", value="reports"),
            app_commands.Choice(name="announcement", value="announcements"),
        ],
    )
    @app_commands.guild_only()
    async def root(
        self,
        interaction: discord.Interaction,
        action: str,
        channel_type: str | None = None,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Handle `/root` actions based on the selected choice."""
        self.log.info("/root invoked action=%s user=%s guild=%s", action, interaction.user.id, interaction.guild_id)

        if action == "channel":
            await self.handle_channel_action(interaction, channel_type, channel)

    async def handle_channel_action(
        self,
        interaction: discord.Interaction,
        channel_type: str | None = None,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Logic for the 'channel' choice."""
        channel_type_labels = {
            "feedback": "feature",
            "reports": "error",
            "announcements": "announcement",
        }

        if channel_type is None:
            await interaction.response.send_message(
                "Select a `channel_type` when using `/root action:channel`.",
                ephemeral=True,
            )
            return

        if channel is None:
            await interaction.response.send_message(
                "Select a `channel` when using `/root action:channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            (
                "Channel test selection saved:\n"
                f"- Type: `{channel_type}` ({channel_type_labels.get(channel_type, 'unknown')})\n"
                f"- Channel: {channel.mention} (`{channel.id}`)"
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Set up the Root cog."""
    await bot.add_cog(Root(bot))
