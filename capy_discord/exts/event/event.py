import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.config import settings
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


class ConfirmDeleteView(BaseView):
    """View to confirm event deletion."""

    def __init__(self) -> None:
        """Initialize the ConfirmDeleteView."""
        super().__init__(timeout=60)
        self.value: bool | None = None

    @ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Button to confirm deletion."""
        self.value = True
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Button to cancel deletion."""
        self.value = False
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()


class Event(commands.Cog):
    """Cog for event-related commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Event cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Event cog initialized")
        # In-memory storage for demonstration.
        self.events: dict[int, list[EventSchema]] = {}
        # Track announcement messages: guild_id -> {event_name: message_id}
        self.event_announcements: dict[int, dict[str, int]] = {}

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
            app_commands.Choice(name="myevents", value="myevents"),
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
            case "myevents":
                await self.handle_myevents_action(interaction)

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
        await self._get_events_for_dropdown(interaction, "edit", self._on_edit_select)

    async def handle_show_action(self, interaction: discord.Interaction) -> None:
        """Handle showing event details."""
        await self._get_events_for_dropdown(interaction, "view", self._on_show_select)

    async def handle_delete_action(self, interaction: discord.Interaction) -> None:
        """Handle event deletion."""
        await self._get_events_for_dropdown(interaction, "delete", self._on_delete_select)

    async def handle_list_action(self, interaction: discord.Interaction) -> None:
        """Handle listing all events."""
        guild_id = interaction.guild_id
        if not guild_id:
            embed = error_embed("No Server", "Events must be listed in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # [DB CALL]: Fetch guild events
        events = self.events.get(guild_id, [])

        if not events:
            embed = error_embed("No Events", "No events found in this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.log.info("Listing events for guild %s", guild_id)

        await interaction.response.defer(ephemeral=True)

        # Separate into upcoming and past events
        now = datetime.now(ZoneInfo("UTC"))
        upcoming_events: list[EventSchema] = []
        past_events: list[EventSchema] = []

        for event in events:
            event_time = self._event_datetime(event)

            if event_time >= now:
                upcoming_events.append(event)
            else:
                past_events.append(event)

        # Sort events
        upcoming_events.sort(key=self._event_datetime)
        past_events.sort(key=self._event_datetime, reverse=True)

        # Build embed
        total_count = len(upcoming_events) + len(past_events)
        embed = success_embed(
            "Events",
            f"Found {total_count} events (Upcoming: {len(upcoming_events)}, Past: {len(past_events)})",
        )

        # Add upcoming events
        for event in upcoming_events:
            embed.add_field(
                name=event.event_name,
                value=self._format_when_where(event),
                inline=False,
            )

        # Add past events with [OLD] prefix
        for event in past_events:
            embed.add_field(
                name=f"[OLD] {event.event_name}",
                value=self._format_when_where(event),
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def handle_announce_action(self, interaction: discord.Interaction) -> None:
        """Handle announcing an event and user registrations."""
        await self._get_events_for_dropdown(interaction, "announce", self._on_announce_select)

    async def handle_myevents_action(self, interaction: discord.Interaction) -> None:
        """Handle showing events the user has registered for via RSVP."""
        guild_id = interaction.guild_id
        guild = interaction.guild
        if not guild_id or not guild:
            embed = error_embed("No Server", "Events must be viewed in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # [DB CALL]: Fetch guild events
        events = self.events.get(guild_id, [])

        if not events:
            embed = error_embed("No Events", "No events found in this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.log.info("Listing registered events for user %s", interaction.user)

        await interaction.response.defer(ephemeral=True)

        # Get upcoming events the user has registered for
        now = datetime.now(ZoneInfo("UTC"))
        registered_events: list[EventSchema] = []

        for event in events:
            event_time = self._event_datetime(event)

            # Only include upcoming events
            if event_time < now:
                continue

            # Check if user has registered for this event
            if await self._is_user_registered(event, guild, interaction.user):
                registered_events.append(event)

        registered_events.sort(key=self._event_datetime)

        # Build embed
        embed = success_embed(
            "Your Registered Events",
            "Events you have registered for by reacting with ✅",
        )

        if not registered_events:
            embed.description = (
                "You haven't registered for any upcoming events.\nReact to event announcements with ✅ to register!"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Add registered events
        for event in registered_events:
            embed.add_field(
                name=event.event_name,
                value=self._format_when_where(event),
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _get_events_for_dropdown(
        self,
        interaction: discord.Interaction,
        action_name: str,
        callback: Callable[[discord.Interaction, EventSchema], Coroutine[Any, Any, None]],
    ) -> None:
        """Generic handler to get events and show dropdown for selection.

        Args:
            interaction: The Discord interaction.
            action_name: Name of the action (e.g., "edit", "view", "delete").
            callback: Async callback to handle the selected event.
        """
        guild_id = interaction.guild_id
        if not guild_id:
            embed = error_embed("No Server", f"Events must be {action_name}ed in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # [DB CALL]: Fetch guild events
        events = self.events.get(guild_id, [])

        if not events:
            embed = error_embed("No Events", f"No events found in this server to {action_name}.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.log.info("Opening event selection for %s in guild %s", action_name, guild_id)

        await interaction.response.defer(ephemeral=True)

        view = EventDropdownView(events, self, f"Select an event to {action_name}", callback)
        await interaction.followup.send(content=f"Select an event to {action_name}:", view=view, ephemeral=True)

        await view.wait()

    @staticmethod
    def _event_datetime(event: EventSchema) -> datetime:
        """Convert event date and time to a timezone-aware datetime in UTC.

        User input is treated as EST, then converted to UTC for storage.

        Args:
            event: The event containing date and time information.

        Returns:
            A UTC timezone-aware datetime object.
        """
        est = ZoneInfo("America/New_York")
        event_time = datetime.combine(event.event_date, event.event_time)
        # Treat user input as EST
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=est)
        # Convert to UTC for storage
        return event_time.astimezone(ZoneInfo("UTC"))

    def _format_event_time_est(self, event: EventSchema) -> str:
        """Format an event's date/time in EST for user-facing display."""
        event_dt_est = self._event_datetime(event).astimezone(ZoneInfo("America/New_York"))
        return event_dt_est.strftime("%B %d, %Y at %I:%M %p EST")

    def _format_when_where(self, event: EventSchema) -> str:
        """Format the when/where field for embeds."""
        time_str = self._format_event_time_est(event)
        return f"**When:** {time_str}\n**Where:** {event.location or 'TBD'}"

    def _apply_event_fields(self, embed: discord.Embed, event: EventSchema) -> None:
        """Append event detail fields to an embed."""
        embed.add_field(name="Event", value=event.event_name, inline=False)
        embed.add_field(name="Date/Time", value=self._format_event_time_est(event), inline=True)
        embed.add_field(name="Location", value=event.location or "TBD", inline=True)
        if event.description:
            embed.add_field(name="Description", value=event.description, inline=False)

    def _get_announcement_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Get the announcement channel from config name.

        Args:
            guild: The guild to search for the announcement channel.

        Returns:
            The announcement channel if found, None otherwise.
        """
        for channel in guild.text_channels:
            if channel.name.lower() == settings.announcement_channel_name.lower():
                return channel
        return None

    async def _is_user_registered(
        self, event: EventSchema, guild: discord.Guild, user: discord.User | discord.Member
    ) -> bool:
        """Check if a user has registered for an event via RSVP reaction.

        Args:
            event: The event to check registration for.
            guild: The guild where the event was announced.
            user: The user to check registration for.

        Returns:
            True if the user has reacted with ✅ to the event announcement, False otherwise.
        """
        # Get announcement messages for this guild
        guild_announcements = self.event_announcements.get(guild.id, {})
        message_id = guild_announcements.get(event.event_name)

        if not message_id:
            return False

        # Try to find the announcement message and check reactions
        announcement_channel = self._get_announcement_channel(guild)

        if not announcement_channel:
            return False

        try:
            message = await announcement_channel.fetch_message(message_id)
            # Check if user reacted with ✅
            for reaction in message.reactions:
                if str(reaction.emoji) == "✅":
                    users = [user async for user in reaction.users()]
                    if user in users:
                        return True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            # Message not found or no permission - skip this event
            self.log.warning("Could not fetch announcement message %s", message_id)
            return False

        return False

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

    async def _on_announce_select(self, interaction: discord.Interaction, selected_event: EventSchema) -> None:
        """Handle event selection for announcement."""
        guild = interaction.guild
        if not guild:
            embed = error_embed("No Server", "Cannot determine server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get the announcement channel
        announcement_channel = self._get_announcement_channel(guild)

        if not announcement_channel:
            embed = error_embed(
                "No Announcement Channel",
                f"Could not find a channel named '{settings.announcement_channel_name}'. "
                "Please rename or create an announcement channel.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if bot has permission to post in the channel
        if not announcement_channel.permissions_for(guild.me).send_messages:
            embed = error_embed(
                "No Permission",
                "I don't have permission to send messages in the announcement channel.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            # Create announcement embed
            announce_embed = self._create_announcement_embed(selected_event)

            # Post to announcement channel
            message = await announcement_channel.send(embed=announce_embed)

            # Add RSVP reactions
            await message.add_reaction("✅")  # Attending
            await message.add_reaction("❌")  # Not attending

            # [DB CALL]: Store announcement message ID for RSVP tracking
            if guild.id not in self.event_announcements:
                self.event_announcements[guild.id] = {}
            self.event_announcements[guild.id][selected_event.event_name] = message.id

            self.log.info(
                "Announced event '%s' to guild %s in channel %s",
                selected_event.event_name,
                guild.id,
                announcement_channel.name,
            )

            success = success_embed(
                "Event Announced",
                f"Event announced successfully in {announcement_channel.mention}!\n"
                "Users can react with ✅ to attend or ❌ to decline.",
            )
            self._apply_event_fields(success, selected_event)
            await interaction.response.send_message(embed=success, ephemeral=True)

        except discord.Forbidden:
            embed = error_embed("Permission Denied", "I don't have permission to send messages in that channel.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            self.log.exception("Failed to announce event")
            embed = error_embed("Announcement Failed", "Failed to announce the event. Please try again.")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    def _create_announcement_embed(self, event: EventSchema) -> discord.Embed:
        """Create an announcement embed for an event."""
        embed = success_embed(
            "Event Announcement",
            event.description or "No description provided.",
        )
        self._apply_event_fields(embed, event)

        embed.add_field(
            name="📋 RSVP",
            value="React with ✅ to attend or ❌ to decline.",
            inline=False,
        )

        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Announced: {now}")
        return embed

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

        embed = success_embed("Event Created", "Your event has been created successfully!")
        self._apply_event_fields(embed, event)
        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Created: {now}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _create_event_embed(self, title: str, description: str, event: EventSchema) -> discord.Embed:
        """Helper to build a success-styled event display embed."""
        embed = success_embed(title, description)
        self._apply_event_fields(embed, event)
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

        embed = self._create_event_embed(
            "Event Updated",
            "Your event has been updated successfully!",
            updated_event,
        )
        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Updated: {now}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _on_show_select(self, interaction: discord.Interaction, selected_event: EventSchema) -> None:
        """Handle event selection for showing details."""
        embed = self._create_event_embed(
            "Event Details",
            "Here are the details for this event.",
            selected_event,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _on_delete_select(self, interaction: discord.Interaction, selected_event: EventSchema) -> None:
        """Handle event selection for deletion."""
        view = ConfirmDeleteView()
        embed = discord.Embed(
            title="Confirm Deletion",
            description=f"Are you sure you want to delete **{selected_event.event_name}**?",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        await view.wait()

        if view.value is True:
            # [DB CALL]: Delete event from guild
            guild_id = interaction.guild_id
            if guild_id:
                guild_events = self.events.setdefault(guild_id, [])
                if selected_event in guild_events:
                    guild_events.remove(selected_event)
                    self.log.info("Deleted event '%s' from guild %s", selected_event.event_name, guild_id)

            success = success_embed("Event Deleted", "The event has been deleted successfully!")
            await interaction.followup.send(embed=success, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Event cog."""
    await bot.add_cog(Event(bot))
