import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.ui.embeds import error_embed, success_embed
from capy_discord.ui.forms import ModelModal
from capy_discord.ui.views import BaseView

from ._schemas import EventSchema


class EventDropdownSelect(ui.Select["EventDropdownView"]):
    """Generic select component for event selection with customizable callback."""

    def __init__(
        self,
        options: list[discord.SelectOption],
        view: "EventDropdownView",
        placeholder: str,
    ) -> None:
        """Initialize the select."""
        super().__init__(placeholder=placeholder, options=options)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle selection by delegating to view's callback."""
        event_idx = int(self.values[0])
        selected_event = self.view_ref.event_list[event_idx]
        await self.view_ref.on_select(interaction, selected_event)
        self.view_ref.stop()


class EventDropdownView(BaseView):
    """Generic view for event selection with customizable callback."""

    def __init__(
        self,
        events: list[EventSchema],
        cog: "Event",
        placeholder: str,
        on_select_callback: Callable[[discord.Interaction, EventSchema], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize the EventDropdownView.

        Args:
            events: List of events to select from.
            cog: Reference to the Event cog.
            placeholder: Placeholder text for the dropdown.
            on_select_callback: Async callback to handle selection.
        """
        super().__init__(timeout=60)
        self.event_list = events
        self.cog = cog
        self.on_select = on_select_callback

        if not events:
            return

        options = [discord.SelectOption(label=event.event_name[:100], value=str(i)) for i, event in enumerate(events)]
        self.add_item(EventDropdownSelect(options=options, view=self, placeholder=placeholder))


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
            app_commands.Choice(name="edit", value="edit"),
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
            case "edit":
                await self.handle_edit_action(interaction)
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

    async def handle_edit_action(self, interaction: discord.Interaction) -> None:
        """Handle event editing."""
        guild_id = interaction.guild_id
        if not guild_id:
            embed = error_embed("No Server", "Events must be edited in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # [DB CALL]: Fetch guild events
        events = self.events.get(guild_id, [])

        if not events:
            embed = error_embed("No Events", "No events found in this server to edit.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.log.info("Opening event selection for editing in guild %s", guild_id)

        await interaction.response.defer(ephemeral=True)

        view = EventDropdownView(events, self, "Select an event to edit", self._on_edit_select)
        await interaction.followup.send(content="Select an event to edit:", view=view, ephemeral=True)

        await view.wait()

    async def _on_edit_select(self, interaction: discord.Interaction, selected_event: EventSchema) -> None:
        """Handle event selection for editing."""
        initial_data = {
            "event_name": selected_event.event_name,
            "event_date": selected_event.event_date.strftime("%m-%d-%Y"),
            "event_time": selected_event.event_time.strftime("%H:%M"),
            "location": selected_event.location,
            "description": selected_event.description,
        }

        self.log.info("Opening edit modal for event '%s'", selected_event.event_name)

        modal = ModelModal(
            model_cls=EventSchema,
            callback=lambda modal_interaction, event: self._handle_event_update(
                modal_interaction, event, selected_event
            ),
            title="Edit Event",
            initial_data=initial_data,
        )
        await interaction.response.send_modal(modal)

    async def handle_show_action(self, interaction: discord.Interaction) -> None:
        """Handle showing event details."""
        guild_id = interaction.guild_id
        if not guild_id:
            embed = error_embed("No Server", "Events must be viewed in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # [DB CALL]: Fetch guild events
        events = self.events.get(guild_id, [])

        if not events:
            embed = error_embed("No Events", "No events found in this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.log.info("Opening event selection for viewing in guild %s", guild_id)

        await interaction.response.defer(ephemeral=True)

        view = EventDropdownView(events, self, "Select an event to view", self._on_show_select)
        await interaction.followup.send(content="Select an event to view:", view=view, ephemeral=True)

        await view.wait()

    async def _on_show_select(self, interaction: discord.Interaction, selected_event: EventSchema) -> None:
        """Handle event selection for showing details."""
        embed = self._create_event_embed(selected_event)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

        event_time = datetime.combine(event.event_date, event.event_time)
        if event_time.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo or ZoneInfo("UTC")
            event_time = event_time.replace(tzinfo=local_tz)

        timestamp = int(event_time.timestamp())
        embed.add_field(name="Date/Time", value=f"<t:{timestamp}:F>", inline=True)
        embed.add_field(name="Location", value=event.location or "TBD", inline=True)

        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Created: {now}")
        return embed

    async def _handle_event_update(
        self, interaction: discord.Interaction, updated_event: EventSchema, original_event: EventSchema
    ) -> None:
        """Process the event update submission."""
        guild_id = interaction.guild_id
        if not guild_id:
            embed = error_embed("No Server", "Events must be updated in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # [DB CALL]: Update event
        guild_events = self.events.setdefault(guild_id, [])
        if original_event in guild_events:
            idx = guild_events.index(original_event)
            guild_events[idx] = updated_event

        self.log.info("Updated event '%s' for guild %s", updated_event.event_name, guild_id)

        embed = self._create_event_embed(updated_event)
        success = success_embed("Event Updated", "Your event has been updated successfully!")
        await interaction.response.send_message(embeds=[success, embed], ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Event cog."""
    await bot.add_cog(Event(bot))
