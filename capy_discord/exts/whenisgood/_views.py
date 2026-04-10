from __future__ import annotations

from typing import Any, TYPE_CHECKING

import discord
from discord import ui

from capy_discord.ui.embeds import error_embed, info_embed, success_embed
from capy_discord.ui.views import BaseView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ._service import AvailabilityPoll, WhenIsGoodService


class PollPickerSelect(ui.Select["PollPickerView"]):
    """Dropdown for choosing which poll to open."""

    def __init__(self, polls: list[AvailabilityPoll]) -> None:
        options = [
            discord.SelectOption(
                label=poll.title[:100],
                description=f"ID {poll.poll_id} • {len(poll.slots)} slot(s) • {len(poll.votes)} voter(s)"[:100],
                value=poll.poll_id,
            )
            for poll in polls[:25]
        ]
        super().__init__(
            placeholder="Choose a poll",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Track the chosen poll on the parent view."""
        if self.view is None:
            return
        self.view.selected_poll_id = self.values[0]
        self.view.confirm.disabled = False
        await interaction.response.edit_message(
            content="Poll selected. Click Confirm to continue.",
            view=self.view,
        )


class PollPickerView(BaseView):
    """View for choosing one of several polls in a guild."""

    def __init__(
        self,
        polls: list[AvailabilityPoll],
        on_confirm: Callable[[discord.Interaction, AvailabilityPoll], Awaitable[Any]],
    ) -> None:
        super().__init__(timeout=180)
        self.polls_by_id = {poll.poll_id: poll for poll in polls[:25]}
        self.on_confirm_callback = on_confirm
        self.selected_poll_id: str | None = None
        self.cancelled = False
        self.add_item(PollPickerSelect(polls))
        self.confirm.disabled = True

    @ui.button(label="Confirm", style=discord.ButtonStyle.success, row=1)
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open the selected poll."""
        if self.selected_poll_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Poll Selected", "Please choose a poll first."),
                ephemeral=True,
            )
            return

        poll = self.polls_by_id[self.selected_poll_id]
        await self.on_confirm_callback(interaction, poll)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Cancel poll selection."""
        self.cancelled = True
        self.disable_all_items()
        await interaction.response.edit_message(
            content=None,
            embed=info_embed("Cancelled", "No poll was selected."),
            view=self,
        )
        self.stop()


class AvailabilitySelect(ui.Select["AvailabilityVoteView"]):
    """Multi-select dropdown for availability choices."""

    def __init__(self, poll: AvailabilityPoll) -> None:
        options = [
            discord.SelectOption(
                label=f"Option {index + 1}",
                description=slot[:100],
                value=str(index),
            )
            for index, slot in enumerate(poll.slots)
        ]
        super().__init__(
            placeholder="Choose all time slots that work for you",
            min_values=1,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Track selections on the parent view."""
        if self.view is None:
            return
        self.view.selected_slots = {int(value) for value in self.values}
        self.view.submit.disabled = False
        await interaction.response.edit_message(
            content="Selections updated. Click Submit Vote to save your availability.",
            view=self.view,
        )


class AvailabilityVoteView(BaseView):
    """Interactive view for recording a user's availability."""

    def __init__(self, poll: AvailabilityPoll, service: WhenIsGoodService) -> None:
        super().__init__(timeout=300)
        self.poll = poll
        self.service = service
        self.selected_slots: set[int] = set()
        self.submitted = False
        self.cancelled = False
        self.add_item(AvailabilitySelect(poll))
        self.submit.disabled = True

    @ui.button(label="Submit Vote", style=discord.ButtonStyle.success, row=1)
    async def submit(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Save the user's availability selections."""
        if not self.selected_slots:
            await interaction.response.send_message(
                embed=error_embed("No Selection", "Choose at least one time slot before submitting."),
                ephemeral=True,
            )
            return

        self.service.record_vote(self.poll, interaction.user.id, self.selected_slots)
        self.submitted = True
        self.disable_all_items()
        await interaction.response.edit_message(
            content=None,
            embeds=[
                success_embed("Availability Saved", "Your response has been recorded."),
                self.service.build_results_embed(self.poll),
            ],
            view=self,
        )
        self.stop()

    @ui.button(label="Show Results", style=discord.ButtonStyle.primary, row=1)
    async def show_results(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Show current poll results without changing the user's vote."""
        await interaction.response.send_message(
            embed=self.service.build_results_embed(self.poll),
            ephemeral=True,
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Cancel the voting flow."""
        self.cancelled = True
        self.disable_all_items()
        await interaction.response.edit_message(
            content=None,
            embed=info_embed("Cancelled", "No availability was submitted."),
            view=self,
        )
        self.stop()
