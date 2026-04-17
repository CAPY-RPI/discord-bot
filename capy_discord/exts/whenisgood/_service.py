from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord

if TYPE_CHECKING:
    from ._schemas import CreateMeetingSchema

SLOT_DURATION_MINUTES = 60
MAX_RESULTS_FIELDS = 12
HEATMAP_BLOCKS = " .:-=+*#%@"


@dataclass(slots=True)
class ParticipantRecord:
    """Participant state stored per meeting."""

    user_id: int
    name: str
    selected_slots: set[int] = field(default_factory=set)
    updated_at: datetime = field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))


@dataclass(slots=True)
class MeetingEvent:
    """Represents a scheduling event and its participants."""

    event_id: str
    guild_id: int
    channel_id: int
    host_id: int
    title: str
    timezone: str
    start_date: date
    end_date: date
    daily_start: time
    daily_end: time
    slots: list[datetime]
    created_at: datetime = field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))
    participants: dict[int, ParticipantRecord] = field(default_factory=dict)
    announcement_message_id: int | None = None
    finalized_slot_index: int | None = None


class WhenIsGoodService:
    """Manage meeting events, participants, and availability overlap."""

    def __init__(self) -> None:
        self.events: dict[str, MeetingEvent] = {}

    def create_event(
        self,
        *,
        guild_id: int,
        channel_id: int,
        host_id: int,
        meeting: CreateMeetingSchema,
    ) -> MeetingEvent:
        """Create a new scheduling event from validated modal data."""
        daily_start, daily_end = meeting.parse_daily_hours()
        event_id = uuid4().hex[:8]
        slots = self._build_slots(
            start_date=meeting.start_date,
            end_date=meeting.end_date,
            daily_start=daily_start,
            daily_end=daily_end,
            timezone=meeting.timezone,
        )
        event = MeetingEvent(
            event_id=event_id,
            guild_id=guild_id,
            channel_id=channel_id,
            host_id=host_id,
            title=meeting.title,
            timezone=meeting.timezone,
            start_date=meeting.start_date,
            end_date=meeting.end_date,
            daily_start=daily_start,
            daily_end=daily_end,
            slots=slots,
        )
        self.events[event_id] = event
        return event

    def list_events_for_guild(self, guild_id: int) -> list[MeetingEvent]:
        """Return guild events, newest first."""
        events = [event for event in self.events.values() if event.guild_id == guild_id]
        events.sort(key=lambda event: event.created_at, reverse=True)
        return events

    def get_event(self, event_id: str) -> MeetingEvent | None:
        """Return an event by id."""
        return self.events.get(event_id)

    def get_guild_event(self, guild_id: int, event_id: str) -> MeetingEvent | None:
        """Return an event only if it belongs to the guild."""
        event = self.get_event(event_id)
        if event is None or event.guild_id != guild_id:
            return None
        return event

    def set_announcement_message(self, event: MeetingEvent, message_id: int) -> None:
        """Track the public announcement message used as the shareable entrypoint."""
        event.announcement_message_id = message_id

    def upsert_participant_name(self, event: MeetingEvent, user_id: int, display_name: str) -> ParticipantRecord:
        """Create or rename a participant record."""
        participant = event.participants.get(user_id)
        if participant is None:
            participant = ParticipantRecord(user_id=user_id, name=display_name)
            event.participants[user_id] = participant
        else:
            participant.name = display_name
            participant.updated_at = datetime.now(ZoneInfo("UTC"))
        return participant

    def get_participant(self, event: MeetingEvent, user_id: int) -> ParticipantRecord | None:
        """Return a participant record if one exists."""
        return event.participants.get(user_id)

    def ensure_participant_name(self, event: MeetingEvent, user_id: int, fallback_name: str) -> ParticipantRecord:
        """Ensure a participant exists, using a fallback name when needed."""
        participant = self.get_participant(event, user_id)
        if participant is None:
            participant = self.upsert_participant_name(event, user_id, fallback_name)
        return participant

    def set_participant_availability(
        self,
        event: MeetingEvent,
        user_id: int,
        name: str,
        selected_slots: set[int],
    ) -> ParticipantRecord:
        """Replace the participant's selected availability."""
        participant = self.ensure_participant_name(event, user_id, name)
        participant.selected_slots = selected_slots
        participant.updated_at = datetime.now(ZoneInfo("UTC"))
        return participant

    def clear_participant_availability(self, event: MeetingEvent, user_id: int) -> None:
        """Clear a participant's availability selections."""
        participant = self.get_participant(event, user_id)
        if participant is not None:
            participant.selected_slots.clear()
            participant.updated_at = datetime.now(ZoneInfo("UTC"))

    def get_overlap_counts(self, event: MeetingEvent) -> list[int]:
        """Return the count of available participants per slot."""
        counts = [0] * len(event.slots)
        for participant in event.participants.values():
            for slot_index in participant.selected_slots:
                if 0 <= slot_index < len(counts):
                    counts[slot_index] += 1
        return counts

    def get_best_slot_indexes(self, event: MeetingEvent) -> list[int]:
        """Return the slot indexes tied for highest overlap."""
        counts = self.get_overlap_counts(event)
        if not counts:
            return []
        max_count = max(counts)
        if max_count == 0:
            return []
        return [index for index, count in enumerate(counts) if count == max_count]

    def finalize_slot(self, event: MeetingEvent, slot_index: int) -> None:
        """Mark an event as finalized at the chosen slot."""
        if not 0 <= slot_index < len(event.slots):
            msg = "Invalid slot index."
            raise ValueError(msg)
        event.finalized_slot_index = slot_index

    def slot_label(self, event: MeetingEvent, slot_index: int) -> str:
        """Return a human-readable slot label in the event timezone."""
        event_tz = ZoneInfo(event.timezone)
        local_slot = event.slots[slot_index].astimezone(event_tz)
        return local_slot.strftime("%a %b %d, %Y %I:%M %p")

    def slot_labels_for_date(self, event: MeetingEvent) -> dict[str, list[tuple[int, str]]]:
        """Group slot labels by local event date."""
        event_tz = ZoneInfo(event.timezone)
        grouped: dict[str, list[tuple[int, str]]] = {}
        for index, slot in enumerate(event.slots):
            local_slot = slot.astimezone(event_tz)
            date_label = local_slot.strftime("%a %b %d")
            grouped.setdefault(date_label, []).append((index, local_slot.strftime("%I:%M %p").lstrip("0")))
        return grouped

    def build_announcement_embed(self, event: MeetingEvent) -> discord.Embed:
        """Build the public event summary embed."""
        participant_count = len(event.participants)
        counts = self.get_overlap_counts(event)
        best_indexes = self.get_best_slot_indexes(event)
        embed = discord.Embed(
            title=f"WhenIsGood: {event.title}",
            description=(
                "Paint your availability with the buttons below. "
                "Participants can join, edit, and view overlap in real time."
            ),
            color=discord.Color.blue(),
            timestamp=event.created_at,
        )
        embed.add_field(name="Event ID", value=event.event_id, inline=True)
        embed.add_field(name="Time Zone", value=event.timezone, inline=True)
        embed.add_field(name="Participants", value=str(participant_count), inline=True)
        embed.add_field(
            name="Range",
            value=(
                f"{event.start_date.isoformat()} to {event.end_date.isoformat()}\n"
                f"{event.daily_start.strftime('%H:%M')} - {event.daily_end.strftime('%H:%M')}"
            ),
            inline=False,
        )
        if best_indexes:
            best_lines = "\n".join(self.slot_label(event, index) for index in best_indexes[:3])
            embed.add_field(name="Best Options", value=best_lines, inline=False)
        else:
            embed.add_field(name="Best Options", value="No availability submitted yet.", inline=False)

        if counts:
            preview_lines = self._build_heatmap_lines(event, counts)
            embed.add_field(name="Overlap Heatmap", value="\n".join(preview_lines), inline=False)

        if event.finalized_slot_index is not None:
            embed.add_field(name="Final Pick", value=self.slot_label(event, event.finalized_slot_index), inline=False)

        embed.set_footer(text="Share the message link so others can join without extra setup.")
        return embed

    def build_results_embed(self, event: MeetingEvent) -> discord.Embed:
        """Build a detailed overlap summary embed."""
        counts = self.get_overlap_counts(event)
        best_indexes = set(self.get_best_slot_indexes(event))
        embed = discord.Embed(
            title=f"Results: {event.title}",
            description=f"{len(event.participants)} participant(s) have joined.",
            color=discord.Color.green(),
        )
        grouped = self.slot_labels_for_date(event)
        for added_fields, (date_label, entries) in enumerate(grouped.items()):
            if added_fields >= MAX_RESULTS_FIELDS:
                break
            lines = []
            for slot_index, time_label in entries:
                marker = "BEST" if slot_index in best_indexes else "    "
                lines.append(f"`{marker}` {time_label} - {counts[slot_index]}")
            embed.add_field(name=date_label, value="\n".join(lines), inline=False)

        if event.finalized_slot_index is not None:
            embed.add_field(name="Final Pick", value=self.slot_label(event, event.finalized_slot_index), inline=False)

        return embed

    def build_export_text(self, event: MeetingEvent) -> str:
        """Return plain text that can be copied into calendar tools or chat."""
        counts = self.get_overlap_counts(event)
        lines = [
            f"{event.title}",
            f"Event ID: {event.event_id}",
            f"Time zone: {event.timezone}",
            "",
            "Slots:",
        ]
        for index, count in enumerate(counts):
            lines.append(f"- {self.slot_label(event, index)} ({count} available)")
        if event.finalized_slot_index is not None:
            lines.extend(["", f"Final pick: {self.slot_label(event, event.finalized_slot_index)}"])
        return "\n".join(lines)

    def _build_slots(
        self,
        *,
        start_date: date,
        end_date: date,
        daily_start: time,
        daily_end: time,
        timezone: str,
    ) -> list[datetime]:
        """Build UTC slot datetimes spanning the configured date/time range."""
        event_tz = ZoneInfo(timezone)
        slots: list[datetime] = []
        current_day = start_date
        step = timedelta(minutes=SLOT_DURATION_MINUTES)
        while current_day <= end_date:
            local_dt = datetime.combine(current_day, daily_start, tzinfo=event_tz)
            day_end = datetime.combine(current_day, daily_end, tzinfo=event_tz)
            while local_dt < day_end:
                slots.append(local_dt.astimezone(ZoneInfo("UTC")))
                local_dt += step
            current_day += timedelta(days=1)
        return slots

    def _build_heatmap_lines(self, event: MeetingEvent, counts: list[int]) -> list[str]:
        """Return compressed heatmap lines grouped by local date."""
        grouped = self.slot_labels_for_date(event)
        max_count = max(counts) if counts else 0
        lines: list[str] = []
        for date_label, entries in grouped.items():
            blocks = "".join(self._count_to_block(counts[index], max_count) for index, _ in entries)
            lines.append(f"{date_label}: {blocks}")
        return lines[:6]

    def _count_to_block(self, count: int, max_count: int) -> str:
        """Map a count to a heatmap density character."""
        if max_count <= 0:
            return HEATMAP_BLOCKS[0]
        scale_index = round((count / max_count) * (len(HEATMAP_BLOCKS) - 1))
        return HEATMAP_BLOCKS[scale_index]
