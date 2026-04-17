from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

from capy_discord.ui.embeds import error_embed, info_embed
from capy_discord.ui.modal import CallbackModal
from capy_discord.ui.views import BaseView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Protocol

    from ._service import MeetingEvent, WhenIsGoodService

    class WhenIsGoodCogProto(Protocol):
        async def open_name_modal(self, interaction: discord.Interaction, event_id: str) -> None:  # type: ignore[misc]
            ...

        async def open_availability_editor(self, interaction: discord.Interaction, event_id: str) -> None:  # type: ignore[misc]
            ...

        async def show_event_results(self, interaction: discord.Interaction, event_id: str) -> None:  # type: ignore[misc]
            ...

        async def share_event(self, interaction: discord.Interaction, event_id: str) -> None:  # type: ignore[misc]
            ...

        async def open_finalize_view(self, interaction: discord.Interaction, event_id: str) -> None:  # type: ignore[misc]
            ...


MAX_EVENT_SELECT_OPTIONS = 25


class ParticipantNameModal(CallbackModal):
    """Collect a participant display name before editing availability."""

    def __init__(self, callback: Callable[[discord.Interaction, str], Awaitable[None]]) -> None:
        """Initialize the participant name modal."""
        self._name_callback = callback
        super().__init__(callback=self._handle_submit, title="Join Schedule")
        self.name_input = ui.TextInput(
            label="Your Name",
            max_length=50,
            placeholder="How should we label you?",
        )
        self.add_item(self.name_input)

    async def _handle_submit(self, interaction: discord.Interaction, _modal: ParticipantNameModal) -> None:
        """Submit the cleaned participant name to the provided callback."""
        await self._name_callback(interaction, str(self.name_input.value).strip())


class EventActionView(BaseView):
    """Public event message view with the main participant actions."""

    def __init__(self, cog: WhenIsGoodCogProto, event_id: str) -> None:
        """Initialize the shared event action view."""
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event_id

    @ui.button(label="Join / Name", style=discord.ButtonStyle.primary, row=0)
    async def join(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Prompt the participant to enter or update their display name."""
        await self.cog.open_name_modal(interaction, self.event_id)

    @ui.button(label="Edit Availability", style=discord.ButtonStyle.success, row=0)
    async def edit(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open the availability editor for this event."""
        await self.cog.open_availability_editor(interaction, self.event_id)

    @ui.button(label="View Results", style=discord.ButtonStyle.secondary, row=0)
    async def results(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Show overlap results for the event."""
        await self.cog.show_event_results(interaction, self.event_id)

    @ui.button(label="Share", style=discord.ButtonStyle.secondary, row=0)
    async def share(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Show the share link and command shortcut."""
        await self.cog.share_event(interaction, self.event_id)

    @ui.button(label="Finalize", style=discord.ButtonStyle.danger, row=0)
    async def finalize(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open the host finalization flow."""
        await self.cog.open_finalize_view(interaction, self.event_id)


class EventPickerSelect(ui.Select["EventPickerView"]):
    """Dropdown used when a guild has several active events."""

    def __init__(self, events: list[MeetingEvent]) -> None:
        """Initialize the event picker select."""
        options = [
            discord.SelectOption(
                label=event.title[:100],
                description=f"ID {event.event_id} - {len(event.participants)} participant(s)"[:100],
                value=event.event_id,
            )
            for event in events[:MAX_EVENT_SELECT_OPTIONS]
        ]
        super().__init__(
            placeholder="Choose an event",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Track the selected event on the parent view."""
        view = self.view
        if view is None:
            return
        view.selected_event_id = self.values[0]
        view.confirm.disabled = False
        await interaction.response.edit_message(
            content="Event selected. Click Confirm to continue.",
            view=view,
        )


class EventPickerView(BaseView):
    """Picker view for resolving one event from a guild."""

    def __init__(
        self,
        events: list[MeetingEvent],
        on_confirm: Callable[[discord.Interaction, MeetingEvent], Awaitable[None]],
    ) -> None:
        """Initialize the event picker view."""
        super().__init__(timeout=180)
        self.events_by_id = {event.event_id: event for event in events[:MAX_EVENT_SELECT_OPTIONS]}
        self.on_confirm_callback = on_confirm
        self.selected_event_id: str | None = None
        self.add_item(EventPickerSelect(events))
        self.confirm.disabled = True

    @ui.button(label="Confirm", style=discord.ButtonStyle.success, row=1)
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Confirm the selected event and run the next step."""
        if self.selected_event_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Event Selected", "Choose an event first."),
                ephemeral=True,
            )
            return
        event = self.events_by_id[self.selected_event_id]
        await self.on_confirm_callback(interaction, event)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Cancel event picking."""
        self.disable_all_items()
        await interaction.response.edit_message(
            embed=info_embed("Cancelled", "No event was selected."),
            view=self,
        )
        self.stop()


class DateSelect(ui.Select["AvailabilityEditorView"]):
    """Select the active date when editing availability."""

    def __init__(self, view: AvailabilityEditorView) -> None:
        """Initialize the date select."""
        grouped = view.service.slot_labels_for_date(view.event)
        options = [
            discord.SelectOption(label=date_label, value=date_label, default=date_label == view.selected_date_label)
            for date_label in grouped
        ]
        super().__init__(
            placeholder="Choose a day",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Switch the editor to another date."""
        view = self.view
        if view is None:
            return
        view.selected_date_label = self.values[0]
        view.pending_selection = view._saved_slots_for_selected_date()
        view.rebuild_items()
        await interaction.response.edit_message(
            embed=view.build_embed(),
            view=view,
        )


class TimeMultiSelect(ui.Select["AvailabilityEditorView"]):
    """Multi-select for the slots on the currently selected date."""

    def __init__(self, view: AvailabilityEditorView) -> None:
        """Initialize the time select for the current date."""
        current_entries = view.grouped_slots[view.selected_date_label]
        options = []
        participant = view.service.get_participant(view.event, view.user_id)
        saved_slots = participant.selected_slots if participant is not None else set()
        for slot_index, time_label in current_entries:
            options.append(
                discord.SelectOption(
                    label=time_label,
                    value=str(slot_index),
                    default=slot_index in saved_slots,
                    description=f"{view.counts[slot_index]} people available",
                )
            )
        super().__init__(
            placeholder="Mark the times that work for you",
            min_values=0,
            max_values=len(options),
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Track the currently selected slot indexes."""
        view = self.view
        if view is None:
            return
        view.pending_selection = {int(value) for value in self.values}
        await interaction.response.edit_message(content="Selection updated. Save when ready.", view=view)


class AvailabilityEditorView(BaseView):
    """Ephemeral editor that approximates the When2Meet grid in Discord."""

    def __init__(
        self,
        *,
        service: WhenIsGoodService,
        event: MeetingEvent,
        user_id: int,
        participant_name: str,
        on_saved: Callable[[discord.Interaction, MeetingEvent], Awaitable[None]],
    ) -> None:
        """Initialize the availability editor."""
        super().__init__(timeout=600)
        self.service = service
        self.event = event
        self.user_id = user_id
        self.participant_name = participant_name
        self.on_saved = on_saved
        self.grouped_slots = self.service.slot_labels_for_date(event)
        self.selected_date_label = next(iter(self.grouped_slots))
        self.pending_selection = self._saved_slots_for_selected_date()
        self.counts = self.service.get_overlap_counts(event)
        self.rebuild_items()

    def _saved_slots_for_selected_date(self) -> set[int]:
        """Return the participant's currently saved slots for the selected date."""
        participant = self.service.get_participant(self.event, self.user_id)
        if participant is None:
            return set()
        current_indexes = {index for index, _ in self.grouped_slots[self.selected_date_label]}
        return {index for index in participant.selected_slots if index in current_indexes}

    def rebuild_items(self) -> None:
        """Rebuild the availability editor controls."""
        self.clear_items()
        self.add_item(DateSelect(self))
        self.add_item(TimeMultiSelect(self))

    def build_embed(self) -> discord.Embed:
        """Build the current editing embed."""
        embed = discord.Embed(
            title=f"Edit Availability: {self.event.title}",
            description=f"Participant: **{self.participant_name}**",
            color=discord.Color.blurple(),
        )
        current_entries = self.grouped_slots[self.selected_date_label]
        participant = self.service.get_participant(self.event, self.user_id)
        saved_slots = participant.selected_slots if participant is not None else set()
        lines = []
        for slot_index, time_label in current_entries:
            marker = "Y" if slot_index in saved_slots else " "
            lines.append(f"`[{marker}]` {time_label} - {self.counts[slot_index]} available")
        embed.add_field(name=self.selected_date_label, value="\n".join(lines), inline=False)
        embed.set_footer(text="Use the dropdowns to choose your free times, then press Save.")
        return embed

    @ui.button(label="Save", style=discord.ButtonStyle.success, row=2)
    async def save(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Persist the availability for the currently selected date."""
        participant = self.service.ensure_participant_name(
            self.event,
            self.user_id,
            self.participant_name,
        )
        other_slots = {
            slot_index
            for slot_index in participant.selected_slots
            if slot_index not in {index for index, _ in self.grouped_slots[self.selected_date_label]}
        }
        updated_slots = other_slots | self.pending_selection
        self.service.set_participant_availability(
            self.event,
            self.user_id,
            self.participant_name,
            updated_slots,
        )
        self.counts = self.service.get_overlap_counts(self.event)
        self.rebuild_items()
        await self.on_saved(interaction, self.event)
        self.stop()

    @ui.button(label="Clear Day", style=discord.ButtonStyle.secondary, row=2)
    async def clear_day(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Remove saved availability for the selected day."""
        participant = self.service.ensure_participant_name(
            self.event,
            self.user_id,
            self.participant_name,
        )
        current_indexes = {index for index, _ in self.grouped_slots[self.selected_date_label]}
        participant.selected_slots = {index for index in participant.selected_slots if index not in current_indexes}
        self.pending_selection = set()
        self.counts = self.service.get_overlap_counts(self.event)
        self.rebuild_items()
        await interaction.response.edit_message(
            embeds=[
                info_embed("Day Cleared", "Saved availability for this day has been removed."),
                self.build_embed(),
            ],
            view=self,
        )

    @ui.button(label="Show Results", style=discord.ButtonStyle.primary, row=2)
    async def show_results(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Show the current overlap summary while editing."""
        await interaction.response.send_message(
            embed=self.service.build_results_embed(self.event),
            ephemeral=True,
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Exit the editor without changing the saved selections for this date."""
        self.disable_all_items()
        await interaction.response.edit_message(
            embed=info_embed("Cancelled", "No changes were saved."),
            view=self,
        )
        self.stop()


class FinalizeSlotSelect(ui.Select["FinalizeView"]):
    """Select used by the host to choose a final slot."""

    def __init__(self, event: MeetingEvent, service: WhenIsGoodService) -> None:
        """Initialize the finalize slot select."""
        counts = service.get_overlap_counts(event)
        options = [
            discord.SelectOption(
                label=service.slot_label(event, index)[:100],
                value=str(index),
                description=f"{counts[index]} participant(s) free"[:100],
            )
            for index in range(min(len(event.slots), MAX_EVENT_SELECT_OPTIONS))
        ]
        super().__init__(
            placeholder="Choose the final meeting slot",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Track the selected final slot."""
        view = self.view
        if view is None:
            return
        view.selected_slot_index = int(self.values[0])
        view.confirm.disabled = False
        await interaction.response.edit_message(content="Slot selected. Click Confirm to finalize.", view=view)


class FinalizeView(BaseView):
    """View used by the host to choose the final meeting time."""

    def __init__(
        self,
        *,
        event: MeetingEvent,
        service: WhenIsGoodService,
        on_confirm: Callable[[discord.Interaction, MeetingEvent, int], Awaitable[None]],
    ) -> None:
        """Initialize the finalize view."""
        super().__init__(timeout=180)
        self.event = event
        self.service = service
        self.on_confirm_callback = on_confirm
        self.selected_slot_index: int | None = None
        self.add_item(FinalizeSlotSelect(event, service))
        self.confirm.disabled = True

    @ui.button(label="Confirm", style=discord.ButtonStyle.success, row=1)
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Confirm the chosen final slot."""
        if self.selected_slot_index is None:
            await interaction.response.send_message(
                embed=error_embed("No Slot Selected", "Choose a slot first."),
                ephemeral=True,
            )
            return
        await self.on_confirm_callback(interaction, self.event, self.selected_slot_index)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Cancel finalization."""
        self.disable_all_items()
        await interaction.response.edit_message(embed=info_embed("Cancelled", "Finalization cancelled."), view=self)
        self.stop()
