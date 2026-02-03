import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.embeds import error_embed, success_embed
from capy_discord.ui.forms import ModelModal

from ._schemas import EventSchema


class Event(commands.Cog):
    """Cog for event-related commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Event cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Event cog initialized")
        # In-memory storage for demonstration.
        self.events: dict[int, list[EventSchema]] = {}

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
        self.log.info("Opening event creation modal for %s", interaction.user)

        modal = ModelModal(
            model_cls=EventSchema,
            callback=self._handle_event_submit,
            title="Create Event",
        )
        await interaction.response.send_modal(modal)

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

    async def _handle_event_submit(self, interaction: discord.Interaction, event: EventSchema) -> None:
        """Process the valid event submission."""
        guild_id = interaction.guild_id
        if not guild_id:
            embed = error_embed("No Server", "Events must be created in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # [DB CALL]: Save event
        self.events.setdefault(guild_id, []).append(event)

        self.log.info("Created event '%s' for guild %s", event.event_name, guild_id)

        embed = self._create_event_embed(event)
        success = success_embed("Event Created", "Your event has been created successfully!")
        await interaction.response.send_message(embeds=[success, embed], ephemeral=True)

    def _create_event_embed(self, event: EventSchema) -> discord.Embed:
        """Helper to build the event display embed."""
        embed = discord.Embed(title=event.event_name, description=event.description)

        event_time = event.event_date
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=ZoneInfo("UTC"))

        embed.add_field(name="Date/Time", value=event_time.strftime("%Y-%m-%d %I:%M %p %Z"), inline=True)
        embed.add_field(name="Location", value=event.location or "TBD", inline=True)

        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Created: {now}")
        return embed


async def setup(bot: commands.Bot) -> None:
    """Set up the Event cog."""
    await bot.add_cog(Event(bot))
