from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.embeds import error_embed, info_embed, success_embed
from capy_discord.ui.forms import ModelModal

from ._schemas import CreateMeetingSchema
from ._service import MeetingEvent, WhenIsGoodService
from ._views import (
    AvailabilityEditorView,
    EventActionView,
    EventPickerView,
    FinalizeView,
    ParticipantNameModal,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class WhenIsGood(commands.Cog):
    """Discord cog for fast group scheduling and meeting coordination."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the scheduling cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.service = WhenIsGoodService()

    @app_commands.command(name="whenisgood", description="Create and manage meeting scheduling polls")
    @app_commands.describe(
        action="Which scheduling action to perform",
        event_id="Optional event id when you want a specific scheduling event",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="create", value="create"),
            app_commands.Choice(name="join", value="join"),
            app_commands.Choice(name="edit", value="edit"),
            app_commands.Choice(name="results", value="results"),
            app_commands.Choice(name="share", value="share"),
            app_commands.Choice(name="finalize", value="finalize"),
            app_commands.Choice(name="export", value="export"),
        ]
    )
    async def whenisgood(self, interaction: discord.Interaction, action: str, event_id: str | None = None) -> None:
        """Dispatch scheduling actions."""
        if action == "create":
            await self.handle_create_action(interaction)
        elif action == "join":
            await self.handle_join_action(interaction, event_id)
        elif action == "edit":
            await self.handle_edit_action(interaction, event_id)
        elif action == "results":
            await self.handle_results_action(interaction, event_id)
        elif action == "share":
            await self.handle_share_action(interaction, event_id)
        elif action == "finalize":
            await self.handle_finalize_action(interaction, event_id)
        elif action == "export":
            await self.handle_export_action(interaction, event_id)

    async def handle_create_action(self, interaction: discord.Interaction) -> None:
        """Open the meeting creation modal."""
        if interaction.guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Server", "Scheduling events must be created in a server."),
                ephemeral=True,
            )
            return
        modal = ModelModal(
            model_cls=CreateMeetingSchema,
            callback=self._handle_create_submit,
            title="Create Scheduling Event",
        )
        await interaction.response.send_modal(modal)

    async def handle_join_action(self, interaction: discord.Interaction, event_id: str | None) -> None:
        """Open the participant name flow for an event."""
        await self._resolve_event_action(
            interaction,
            event_id=event_id,
            on_selected=lambda action_interaction, event: self.open_name_modal(action_interaction, event.event_id),
            empty_message="Create a scheduling event first with `/whenisgood action:create`.",
            selection_prompt="Select which scheduling event you want to join:",
        )

    async def handle_edit_action(self, interaction: discord.Interaction, event_id: str | None) -> None:
        """Open the availability editor for an event."""
        await self._resolve_event_action(
            interaction,
            event_id=event_id,
            on_selected=lambda action_interaction, event: self.open_availability_editor(
                action_interaction,
                event.event_id,
            ),
            empty_message="Create a scheduling event first with `/whenisgood action:create`.",
            selection_prompt="Select which scheduling event you want to edit:",
        )

    async def handle_results_action(self, interaction: discord.Interaction, event_id: str | None) -> None:
        """Show overlap results for an event."""
        await self._resolve_event_action(
            interaction,
            event_id=event_id,
            on_selected=lambda action_interaction, event: self.show_event_results(action_interaction, event.event_id),
            empty_message="Create a scheduling event first with `/whenisgood action:create`.",
            selection_prompt="Select which scheduling event results you want to view:",
        )

    async def handle_share_action(self, interaction: discord.Interaction, event_id: str | None) -> None:
        """Show the share link and join instructions for an event."""
        await self._resolve_event_action(
            interaction,
            event_id=event_id,
            on_selected=lambda action_interaction, event: self.share_event(action_interaction, event.event_id),
            empty_message="Create a scheduling event first with `/whenisgood action:create`.",
            selection_prompt="Select which scheduling event you want to share:",
        )

    async def handle_finalize_action(self, interaction: discord.Interaction, event_id: str | None) -> None:
        """Open the finalization flow for the host."""
        await self._resolve_event_action(
            interaction,
            event_id=event_id,
            on_selected=lambda action_interaction, event: self.open_finalize_view(action_interaction, event.event_id),
            empty_message="Create a scheduling event first with `/whenisgood action:create`.",
            selection_prompt="Select which scheduling event you want to finalize:",
        )

    async def handle_export_action(self, interaction: discord.Interaction, event_id: str | None) -> None:
        """Show export text for external calendar use."""
        await self._resolve_event_action(
            interaction,
            event_id=event_id,
            on_selected=lambda action_interaction, event: self.export_event(action_interaction, event.event_id),
            empty_message="Create a scheduling event first with `/whenisgood action:create`.",
            selection_prompt="Select which scheduling event you want to export:",
        )

    async def _handle_create_submit(self, interaction: discord.Interaction, meeting: CreateMeetingSchema) -> None:
        """Create an event, post the shared announcement, and return the share link."""
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Server", "Scheduling events must be created in a server channel."),
                ephemeral=True,
            )
            return

        event = self.service.create_event(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            host_id=interaction.user.id,
            meeting=meeting,
        )
        self.service.upsert_participant_name(event, interaction.user.id, interaction.user.display_name)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            await interaction.response.send_message(
                embed=error_embed("Unsupported Channel", "Use this command in a text channel or thread."),
                ephemeral=True,
            )
            return

        announcement = await channel.send(
            embeds=[self.service.build_announcement_embed(event)],
            view=EventActionView(self, event.event_id),
        )
        self.service.set_announcement_message(event, announcement.id)
        self.log.info("Created scheduling event %s in guild %s", event.event_id, interaction.guild_id)

        await interaction.response.send_message(
            embeds=[
                success_embed("Scheduling Event Created", "Your event is live and ready to share."),
                info_embed(
                    "Share Link",
                    f"{announcement.jump_url}\n\nQuick join: `/whenisgood action:join event_id:{event.event_id}`",
                ),
            ],
            ephemeral=True,
        )

    async def open_name_modal(self, interaction: discord.Interaction, event_id: str) -> None:
        """Open a simple modal so the participant can set their display name."""
        event = self._require_event(interaction.guild_id, event_id)
        if event is None:
            await self._send_missing_event(interaction, event_id)
            return
        participant = self.service.get_participant(event, interaction.user.id)
        if participant is not None:
            await self._open_editor_for_event(interaction, event, participant.name)
            return
        await interaction.response.send_modal(
            ParticipantNameModal(
                lambda modal_interaction, name: self._save_name_and_edit(modal_interaction, event, name)
            )
        )

    async def open_availability_editor(self, interaction: discord.Interaction, event_id: str) -> None:
        """Open the availability editor, prompting for a name first if needed."""
        event = self._require_event(interaction.guild_id, event_id)
        if event is None:
            await self._send_missing_event(interaction, event_id)
            return
        participant = self.service.get_participant(event, interaction.user.id)
        if participant is None:
            await interaction.response.send_modal(
                ParticipantNameModal(
                    lambda modal_interaction, name: self._save_name_and_edit(modal_interaction, event, name)
                )
            )
            return
        await self._open_editor_for_event(interaction, event, participant.name)

    async def show_event_results(self, interaction: discord.Interaction, event_id: str) -> None:
        """Send the detailed overlap results embed."""
        event = self._require_event(interaction.guild_id, event_id)
        if event is None:
            await self._send_missing_event(interaction, event_id)
            return
        await interaction.response.send_message(embed=self.service.build_results_embed(event), ephemeral=True)

    async def share_event(self, interaction: discord.Interaction, event_id: str) -> None:
        """Send sharing instructions and the public jump URL for an event."""
        event = self._require_event(interaction.guild_id, event_id)
        if event is None:
            await self._send_missing_event(interaction, event_id)
            return
        jump_url = await self._get_jump_url(event)
        await interaction.response.send_message(
            embed=info_embed(
                "Share This Event",
                f"Public message: {jump_url}\n\nJoin shortcut: `/whenisgood action:join event_id:{event.event_id}`",
            ),
            ephemeral=True,
        )

    async def open_finalize_view(self, interaction: discord.Interaction, event_id: str) -> None:
        """Open a host-only view for choosing the final meeting time."""
        event = self._require_event(interaction.guild_id, event_id)
        if event is None:
            await self._send_missing_event(interaction, event_id)
            return
        if interaction.user.id != event.host_id:
            await interaction.response.send_message(
                embed=error_embed("Not Allowed", "Only the host can finalize this event."),
                ephemeral=True,
            )
            return
        view = FinalizeView(event=event, service=self.service, on_confirm=self._finalize_slot)
        await view.reply(
            interaction,
            embed=info_embed("Finalize Meeting", "Choose the slot the group wants to lock in."),
            ephemeral=True,
        )

    async def export_event(self, interaction: discord.Interaction, event_id: str) -> None:
        """Send export-ready plain text for the event."""
        event = self._require_event(interaction.guild_id, event_id)
        if event is None:
            await self._send_missing_event(interaction, event_id)
            return
        export_text = self.service.build_export_text(event)
        await interaction.response.send_message(
            content=f"```text\n{export_text}\n```",
            ephemeral=True,
        )

    async def _save_name_and_edit(
        self,
        interaction: discord.Interaction,
        event: MeetingEvent,
        display_name: str,
    ) -> None:
        """Store the participant name and immediately open the availability editor."""
        self.service.upsert_participant_name(event, interaction.user.id, display_name)
        await self._open_editor_for_event(interaction, event, display_name)

    async def _open_editor_for_event(
        self,
        interaction: discord.Interaction,
        event: MeetingEvent,
        participant_name: str,
    ) -> None:
        """Open the main availability editor for a participant."""
        view = AvailabilityEditorView(
            service=self.service,
            event=event,
            user_id=interaction.user.id,
            participant_name=participant_name,
            on_saved=self._after_editor_saved,
        )
        await view.reply(
            interaction,
            embeds=[view.build_embed()],
            ephemeral=True,
        )

    async def _after_editor_saved(self, interaction: discord.Interaction, event: MeetingEvent) -> None:
        """Refresh the public event message and confirm the save."""
        await self._refresh_announcement_message(event)
        confirmation = success_embed(
            "Availability Saved",
            "Your availability was updated and overlap has been refreshed.",
        )
        editor_view = AvailabilityEditorView(
            service=self.service,
            event=event,
            user_id=interaction.user.id,
            participant_name=self.service.ensure_participant_name(
                event,
                interaction.user.id,
                interaction.user.display_name,
            ).name,
            on_saved=self._after_editor_saved,
        )
        await interaction.response.edit_message(
            embeds=[confirmation, editor_view.build_embed()],
            view=editor_view,
        )

    async def _finalize_slot(self, interaction: discord.Interaction, event: MeetingEvent, slot_index: int) -> None:
        """Persist the final human decision and refresh the public event message."""
        self.service.finalize_slot(event, slot_index)
        await self._refresh_announcement_message(event)
        await interaction.response.edit_message(
            embed=success_embed(
                "Meeting Finalized",
                f"Final pick: {self.service.slot_label(event, slot_index)}",
            ),
            view=None,
        )

    async def _refresh_announcement_message(self, event: MeetingEvent) -> None:
        """Refresh the shared event announcement so everyone sees new overlap."""
        if event.announcement_message_id is None:
            return
        channel = self.bot.get_channel(event.channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            return
        try:
            message = await channel.fetch_message(event.announcement_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            self.log.warning("Could not refresh scheduling announcement for event %s", event.event_id)
            return
        await message.edit(
            embeds=[self.service.build_announcement_embed(event)],
            view=EventActionView(self, event.event_id),
        )

    async def _resolve_event_action(
        self,
        interaction: discord.Interaction,
        *,
        event_id: str | None,
        on_selected: Callable[[discord.Interaction, MeetingEvent], Awaitable[None]],
        empty_message: str,
        selection_prompt: str,
    ) -> None:
        """Resolve a single event by id or by presenting an event picker."""
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Server", "Scheduling actions must be used in a server."),
                ephemeral=True,
            )
            return
        if event_id:
            event = self.service.get_guild_event(guild_id, event_id)
            if event is None:
                await self._send_missing_event(interaction, event_id)
                return
            await on_selected(interaction, event)
            return

        events = self.service.list_events_for_guild(guild_id)
        if not events:
            await interaction.response.send_message(embed=error_embed("No Events", empty_message), ephemeral=True)
            return
        if len(events) == 1:
            await on_selected(interaction, events[0])
            return

        await interaction.response.defer(ephemeral=True)
        picker = EventPickerView(events, on_selected)
        await interaction.followup.send(content=selection_prompt, view=picker, ephemeral=True)

    def _require_event(self, guild_id: int | None, event_id: str) -> MeetingEvent | None:
        """Return the guild event when available."""
        if guild_id is None:
            return None
        return self.service.get_guild_event(guild_id, event_id)

    async def _send_missing_event(self, interaction: discord.Interaction, event_id: str) -> None:
        """Send a standard missing-event error."""
        await interaction.response.send_message(
            embed=error_embed("Event Not Found", f"Could not find scheduling event `{event_id}` in this server."),
            ephemeral=True,
        )

    async def _get_jump_url(self, event: MeetingEvent) -> str:
        """Return the public jump url when the announcement still exists."""
        if event.announcement_message_id is None:
            return "Announcement message not found."
        channel = self.bot.get_channel(event.channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            return "Announcement channel unavailable."
        try:
            message = await channel.fetch_message(event.announcement_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return "Announcement message unavailable."
        return message.jump_url


async def setup(bot: commands.Bot) -> None:
    """Register the scheduling cog."""
    await bot.add_cog(WhenIsGood(bot))
