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
                await self.handle_create_action(interaction)
            case "update":
                await self.handle_update_action(interaction)
            case "show":
                await self.handle_show_action(interaction)
            case "delete":
                await self.handle_delete_action(interaction)
            case "list":
                await self.handle_list_action(interaction)
            case "announce":
                await self.handle_announce_action(interaction)

    async def handle_create_action(self, interaction: discord.Interaction) -> None:
        """Handle event creation."""
        await interaction.response.send_message("Event created successfully.")

    async def handle_update_action(self, interaction: discord.Interaction) -> None:
        """Handle event updating."""
        await interaction.response.send_message("Event updated successfully.")

    async def handle_show_action(self, interaction: discord.Interaction) -> None:
        """Handle showing event details."""
        await interaction.response.send_message("Event details displayed.")

    async def handle_delete_action(self, interaction: discord.Interaction) -> None:
        """Handle event deletion."""
        await interaction.response.send_message("Event deleted successfully.")

    async def handle_list_action(self, interaction: discord.Interaction) -> None:
        """Handle listing all events."""
        await interaction.response.send_message("List of events displayed.")

    async def handle_announce_action(self, interaction: discord.Interaction) -> None:
        """Handle announcing an event."""
        await interaction.response.send_message("Event announced successfully.")


async def setup(bot: commands.Bot) -> None:
    """Set up the Event cog."""
    await bot.add_cog(Event(bot))
