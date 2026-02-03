import logging

import discord
from discord import app_commands
from discord.ext import commands


class Event(commands.Cog):
    """Cog for event-related commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Event cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Event cog initialized")

    @app_commands.command(name="event", description="Manage events")
    @app_commands.describe(action="The action to perform with events")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="create", value="create"),
            app_commands.Choice(name="update", value="update"),
            app_commands.Choice(name="show", value="show"),
            app_commands.Choice(name="delete", value="delete"),
            app_commands.Choice(name="list", value="list"),
            app_commands.Choice(name="announce", value="announce"),
        ]
    )
    async def event(self, interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
        """Manage events based on the action specified."""
        match action.value:
            case "create":
                await interaction.response.send_message("Create event action")
            case "update":
                await interaction.response.send_message("Update event action")
            case "show":
                await interaction.response.send_message("Show event action")
            case "delete":
                await interaction.response.send_message("Delete event action")
            case "list":
                await interaction.response.send_message("List events action")
            case "announce":
                await interaction.response.send_message("Announce event action")


async def setup(bot: commands.Bot) -> None:
    """Set up the Event cog."""
    await bot.add_cog(Event(bot))
