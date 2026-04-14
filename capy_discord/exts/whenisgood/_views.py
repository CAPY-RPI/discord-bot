from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any, TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord
from discord import ui

from capy_discord.ui.embeds import error_embed, info_embed, success_embed
from capy_discord.ui.modal import CallbackModal
from capy_discord.ui.views import BaseView

from ._schemas import MAX_POLL_SLOTS, MIN_POLL_SLOTS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ._service import AvailabilityPoll, WhenIsGoodService

CALENDAR_PAGE_SIZE = 15
CALENDAR_MONTH_COUNT = 12
MONTHS_PER_YEAR = 12
WEEKLY_START_HOUR = 8
WEEKLY_END_HOUR = 22
MINUTES_PER_HALF_HOUR = 30
TIME_PAGE_SIZE = 4


class CalendarTimeModal(CallbackModal):
    """Collect the time label for the currently selected day."""

    def __init__(self, view: CalendarPollBuilderView) -> None:
        """Initialize the time entry modal."""
        super().__init__(callback=view.handle_time_submit, title="Add Time Slot")
        self.view_ref = view
        self.time_input = ui.TextInput(
            label="Time",
            placeholder="7:00 PM or 6:00-8:00 PM",
            max_length=50,
        )
        self.add_item(self.time_input)


class CalendarMonthSelect(ui.Select["CalendarPollBuilderView"]):
    """Dropdown for switching between nearby months."""

    def __init__(self, view: CalendarPollBuilderView) -> None:
        """Initialize the month dropdown."""
        options = [
            discord.SelectOption(
                label=month_date.strftime("%B %Y"),
                value=month_date.isoformat(),
                default=month_date == view.current_month,
            )
            for month_date in view.available_months
        ]
        super().__init__(
            placeholder="Choose a month",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Switch the builder to the selected month."""
        view = self.view
        if view is None:
            return
        view.current_month = date.fromisoformat(self.values[0])
        view.page_index = 0
        view.selected_date = None
        view.rebuild_items()
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class CalendarDayButton(ui.Button["CalendarPollBuilderView"]):
    """Button representing a single day in the current page."""

    def __init__(self, day_value: date | None, *, selected: bool, row: int) -> None:
        """Initialize a day button for the calendar page."""
        if day_value is None:
            super().__init__(label=" ", style=discord.ButtonStyle.secondary, disabled=True, row=row)
            self.day_value = None
            return

        style = discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary
        super().__init__(label=str(day_value.day), style=style, row=row)
        self.day_value = day_value

    async def callback(self, interaction: discord.Interaction) -> None:
        """Set the current active day."""
        view = self.view
        if view is None or self.day_value is None:
            return
        view.selected_date = self.day_value
        view.rebuild_items()
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class CalendarPageButton(ui.Button["CalendarPollBuilderView"]):
    """Navigate between chunks of days in the month."""

    def __init__(self, *, label: str, step: int, row: int, disabled: bool) -> None:
        """Initialize a paging button."""
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=row, disabled=disabled)
        self.step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        """Change the current day page."""
        view = self.view
        if view is None:
            return
        view.page_index += self.step
        view.selected_date = None
        view.rebuild_items()
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class CalendarAddTimeButton(ui.Button["CalendarPollBuilderView"]):
    """Open the time-entry modal for the selected day."""

    def __init__(self, *, disabled: bool, row: int) -> None:
        """Initialize the add-time button."""
        super().__init__(label="Add Time", style=discord.ButtonStyle.success, row=row, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Launch the time modal."""
        if self.view is None:
            return
        if self.view.selected_date is None:
            await interaction.response.send_message(
                embed=error_embed("No Date Selected", "Choose a date before adding a time."),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(CalendarTimeModal(self.view))


class CalendarFinishButton(ui.Button["CalendarPollBuilderView"]):
    """Finalize the poll once enough slots are present."""

    def __init__(self, *, disabled: bool, row: int) -> None:
        """Initialize the finish button."""
        super().__init__(label="Finish", style=discord.ButtonStyle.success, row=row, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Create the poll from the collected slots."""
        if self.view is None:
            return
        await self.view.finish(interaction)


class CalendarCancelButton(ui.Button["CalendarPollBuilderView"]):
    """Cancel the calendar poll builder."""

    def __init__(self, *, row: int) -> None:
        """Initialize the cancel button."""
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Cancel poll creation."""
        if self.view is None:
            return
        self.view.disable_all_items()
        await interaction.response.edit_message(
            embed=info_embed("Cancelled", "Calendar poll creation was cancelled."),
            view=self.view,
        )
        self.view.stop()


class CalendarPollBuilderView(BaseView):
    """Pseudo-calendar builder that turns date selections into poll slots."""

    def __init__(
        self,
        *,
        service: WhenIsGoodService,
        guild_id: int,
        creator_id: int,
        title: str,
        description: str,
    ) -> None:
        """Initialize the calendar poll builder."""
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.creator_id = creator_id
        self.title = title
        self.description = description
        self.selected_date: date | None = None
        self.page_index = 0
        self.slots: list[str] = []
        today = datetime.now(ZoneInfo("America/New_York")).date()
        self.available_months = self._build_available_months(today)
        self.current_month = self.available_months[0]
        self.rebuild_items()

    def _build_available_months(self, start_day: date) -> list[date]:
        """Return the first day of the current month and the next few months."""
        first_month = start_day.replace(day=1)
        months = [first_month]
        year = first_month.year
        month = first_month.month
        for _ in range(CALENDAR_MONTH_COUNT - 1):
            month += 1
            if month > MONTHS_PER_YEAR:
                month = 1
                year += 1
            months.append(date(year, month, 1))
        return months

    def _days_for_current_page(self) -> list[date | None]:
        """Return the chunk of days shown on the current page."""
        _, day_count = calendar.monthrange(self.current_month.year, self.current_month.month)
        month_days = [
            date(self.current_month.year, self.current_month.month, day_number)
            for day_number in range(1, day_count + 1)
        ]
        start = self.page_index * CALENDAR_PAGE_SIZE
        page_days: list[date | None] = []
        page_days.extend(month_days[start : start + CALENDAR_PAGE_SIZE])
        while len(page_days) < CALENDAR_PAGE_SIZE:
            page_days.append(None)
        return page_days

    def _max_page_index(self) -> int:
        """Return the highest valid page index for the current month."""
        _, day_count = calendar.monthrange(self.current_month.year, self.current_month.month)
        return max((day_count - 1) // CALENDAR_PAGE_SIZE, 0)

    def rebuild_items(self) -> None:
        """Rebuild the dynamic calendar controls."""
        self.clear_items()
        self.add_item(CalendarMonthSelect(self))

        for index, day_value in enumerate(self._days_for_current_page()):
            row = 1 + index // 5
            self.add_item(CalendarDayButton(day_value, selected=day_value == self.selected_date, row=row))

        self.add_item(CalendarPageButton(label="Prev", step=-1, row=4, disabled=self.page_index <= 0))
        self.add_item(
            CalendarPageButton(
                label="Next",
                step=1,
                row=4,
                disabled=self.page_index >= self._max_page_index(),
            )
        )
        self.add_item(CalendarAddTimeButton(disabled=self.selected_date is None, row=4))
        self.add_item(CalendarFinishButton(disabled=len(self.slots) < MIN_POLL_SLOTS, row=4))
        self.add_item(CalendarCancelButton(row=4))

    def build_embed(self) -> discord.Embed:
        """Build the current calendar builder status embed."""
        embed = discord.Embed(
            title=f"Calendar Builder: {self.title}",
            description=self.description or "Choose a day, add a time, and build your availability poll.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Month", value=self.current_month.strftime("%B %Y"), inline=True)
        embed.add_field(
            name="Selected Date",
            value=self.selected_date.strftime("%b %d, %Y") if self.selected_date else "None",
            inline=True,
        )
        embed.add_field(name="Slots Added", value=str(len(self.slots)), inline=True)

        if self.slots:
            preview = "\n".join(f"{index + 1}. {slot}" for index, slot in enumerate(self.slots[-10:]))
            embed.add_field(name="Current Slots", value=preview, inline=False)
        else:
            embed.add_field(name="Current Slots", value="No slots added yet.", inline=False)

        embed.set_footer(text="Use Add Time after choosing a date. Finish unlocks after at least 2 slots.")
        return embed

    async def handle_time_submit(self, interaction: discord.Interaction, modal: CalendarTimeModal) -> None:
        """Convert a selected date and typed time into a poll slot."""
        if self.selected_date is None:
            await interaction.response.send_message(
                embed=error_embed("No Date Selected", "Choose a date before adding a time."),
                ephemeral=True,
            )
            return

        time_label = str(modal.time_input.value).strip()
        if not time_label:
            await interaction.response.send_message(
                embed=error_embed("Missing Time", "Enter a time label before submitting."),
                ephemeral=True,
            )
            return

        slot_label = f"{self.selected_date.strftime('%a %b %d, %Y')} at {time_label}"
        if slot_label in self.slots:
            await interaction.response.send_message(
                embed=error_embed("Duplicate Slot", "That date and time is already in the poll."),
                ephemeral=True,
            )
            return
        if len(self.slots) >= MAX_POLL_SLOTS:
            await interaction.response.send_message(
                embed=error_embed("Too Many Slots", f"Calendar polls are limited to {MAX_POLL_SLOTS} slots."),
                ephemeral=True,
            )
            return

        self.slots.append(slot_label)
        self.rebuild_items()

        if self.message is not None:
            await self.message.edit(embed=self.build_embed(), view=self)

        await interaction.response.send_message(
            embed=success_embed("Time Added", f"Added `{slot_label}` to the poll draft."),
            ephemeral=True,
        )

    async def finish(self, interaction: discord.Interaction) -> None:
        """Create the poll and replace the builder UI with the final summary."""
        if len(self.slots) < MIN_POLL_SLOTS:
            await interaction.response.send_message(
                embed=error_embed("Not Enough Slots", f"Add at least {MIN_POLL_SLOTS} slots before finishing."),
                ephemeral=True,
            )
            return

        poll = self.service.create_poll(
            guild_id=self.guild_id,
            creator_id=self.creator_id,
            title=self.title,
            description=self.description,
            slots=self.slots,
        )
        self.disable_all_items()
        await interaction.response.edit_message(
            embeds=[
                success_embed(
                    "Availability Poll Created",
                    f"Your calendar poll is ready. Poll ID: `{poll.poll_id}`.",
                ),
                self.service.build_poll_embed(poll),
            ],
            view=self,
        )
        self.stop()


WEEK_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class WeeklyTimeSelect(ui.Select["WeeklyPollBuilderView"]):
    """Select representing which days (Mon-Sun) are chosen for a given time row."""

    def __init__(self, view: WeeklyPollBuilderView, time_label: str, row: int) -> None:
        options = [discord.SelectOption(label=day, value=str(idx)) for idx, day in enumerate(WEEK_DAYS)]
        super().__init__(
            placeholder=f"Days for {time_label}",
            min_values=0,
            max_values=len(options),
            options=options,
            row=row,
        )
        self.view_ref = view
        self.time_label = time_label

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None:
            return
        # Store selected weekday indices for this time label
        view.time_selections[self.time_label] = {int(v) for v in self.values}
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class WeeklyPollBuilderView(BaseView):
    """Builder that shows a weekly (Mon-Sun) grid of times to choose and create poll slots."""

    def __init__(
        self,
        *,
        service: WhenIsGoodService,
        guild_id: int,
        creator_id: int,
        title: str,
        description: str,
    ) -> None:
        super().__init__(timeout=600)
        self.service = service
        self.guild_id = guild_id
        self.creator_id = creator_id
        self.title = title
        self.description = description
        self.time_labels = self._build_default_times()
        self.page_index = 0
        self.time_selections: dict[str, set[int]] = {}
        self.slots: list[str] = []
        self.rebuild_items()

    def _build_default_times(self) -> list[str]:
        """Build half-hour time labels used in the weekly grid."""
        labels: list[str] = []
        for hour in range(WEEKLY_START_HOUR, WEEKLY_END_HOUR + 1):
            for minute in (0, MINUTES_PER_HALF_HOUR):
                if hour == WEEKLY_END_HOUR and minute == MINUTES_PER_HALF_HOUR:
                    continue
                dt = datetime(2000, 1, 1, hour, minute, tzinfo=ZoneInfo("UTC"))
                labels.append(dt.strftime("%I:%M %p").lstrip("0"))
        return labels

    def _max_page_index(self) -> int:
        return max((len(self.time_labels) - 1) // TIME_PAGE_SIZE, 0)

    def _times_for_page(self) -> list[str]:
        start = self.page_index * TIME_PAGE_SIZE
        return self.time_labels[start : start + TIME_PAGE_SIZE]

    def rebuild_items(self) -> None:
        """Rebuild the weekly grid controls."""
        self.clear_items()
        for idx, time_label in enumerate(self._times_for_page()):
            self.add_item(WeeklyTimeSelect(self, time_label, row=idx))

        prev_disabled = self.page_index <= 0
        next_disabled = self.page_index >= self._max_page_index()
        self.add_item(CalendarPageButton(label="Prev", step=-1, row=4, disabled=prev_disabled))
        self.add_item(CalendarPageButton(label="Next", step=1, row=4, disabled=next_disabled))
        self.add_item(self.add_time)
        self.add_item(CalendarFinishButton(disabled=len(self.slots) < MIN_POLL_SLOTS, row=4))
        self.add_item(CalendarCancelButton(row=4))

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"Weekly Builder: {self.title}",
            description=self.description or "Choose times and pick days (Mon-Sun) to add slots.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Page", value=f"{self.page_index + 1} / {self._max_page_index() + 1}", inline=True)
        embed.add_field(name="Slots Added", value=str(len(self.slots)), inline=True)

        page_times = self._times_for_page()
        rows: list[str] = []
        for time_label in page_times:
            sel = self.time_selections.get(time_label, set())
            days = ", ".join(WEEK_DAYS[i] for i in sorted(sel)) if sel else "(none)"
            rows.append(f"**{time_label}** - {days}")

        if rows:
            embed.add_field(name="Current Page", value="\n".join(rows), inline=False)
        else:
            embed.add_field(name="Current Page", value="No times.", inline=False)

        if self.slots:
            preview = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(self.slots[-20:]))
            embed.add_field(name="Slots Preview", value=preview, inline=False)

        embed.set_footer(text="Pick days for times, click Add Time to append slots, then finish when ready.")
        return embed

    async def finish(self, interaction: discord.Interaction) -> None:
        """Create the weekly poll and replace the builder UI with the final summary."""
        if len(self.slots) < MIN_POLL_SLOTS:
            await interaction.response.send_message(
                embed=error_embed("Not Enough Slots", f"Add at least {MIN_POLL_SLOTS} slots before finishing."),
                ephemeral=True,
            )
            return

        poll = self.service.create_poll(
            guild_id=self.guild_id,
            creator_id=self.creator_id,
            title=self.title,
            description=self.description,
            slots=self.slots,
        )
        self.disable_all_items()
        await interaction.response.edit_message(
            embeds=[
                success_embed(
                    "Availability Poll Created",
                    f"Your weekly poll is ready. Poll ID: `{poll.poll_id}`.",
                ),
                self.service.build_poll_embed(poll),
            ],
            view=self,
        )
        self.stop()

    async def handle_time_submit(self, interaction: discord.Interaction, _modal: CalendarTimeModal) -> None:
        """Reject freeform time entry for the weekly builder."""
        await interaction.response.send_message(
            embed=error_embed(
                "Unsupported",
                "This builder does not accept freeform times.",
            ),
            ephemeral=True,
        )

    @ui.button(label="Add Time", style=discord.ButtonStyle.success, row=4)
    async def add_time(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Convert selected day/time pairs on the current page into poll slots."""
        page_times = self._times_for_page()
        added = 0
        for time_label in page_times:
            sel = self.time_selections.get(time_label, set())
            for day_idx in sorted(sel):
                slot = f"{WEEK_DAYS[day_idx]} {time_label}"
                if slot not in self.slots and len(self.slots) < MAX_POLL_SLOTS:
                    self.slots.append(slot)
                    added += 1

        if added == 0:
            await interaction.response.send_message(
                embed=error_embed("No Selection", "No new day/time combinations selected."),
                ephemeral=True,
            )
            return

        self.rebuild_items()
        if self.message is not None:
            await self.message.edit(embed=self.build_embed(), view=self)

        await interaction.response.send_message(
            embed=success_embed("Added", f"Added {added} slot(s)."),
            ephemeral=True,
        )


class PollPickerSelect(ui.Select["PollPickerView"]):
    """Dropdown for choosing which poll to open."""

    def __init__(self, polls: list[AvailabilityPoll]) -> None:
        """Initialize the poll picker dropdown."""
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
        """Initialize the poll picker view."""
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
        """Initialize the availability selector."""
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
        """Initialize the voting view."""
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
