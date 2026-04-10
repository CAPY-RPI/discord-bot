from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord


@dataclass(slots=True)
class AvailabilityPoll:
    """In-memory availability poll state."""

    poll_id: str
    guild_id: int
    creator_id: int
    title: str
    description: str
    slots: list[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))
    votes: dict[int, set[int]] = field(default_factory=dict)


class WhenIsGoodService:
    """Create polls, record votes, and summarize results."""

    def __init__(self) -> None:
        self.polls: dict[str, AvailabilityPoll] = {}
        self.latest_poll_by_guild: dict[int, str] = {}

    def create_poll(
        self,
        *,
        guild_id: int,
        creator_id: int,
        title: str,
        description: str,
        slots: list[str],
    ) -> AvailabilityPoll:
        """Create and store a new availability poll."""
        poll_id = uuid4().hex[:8]
        poll = AvailabilityPoll(
            poll_id=poll_id,
            guild_id=guild_id,
            creator_id=creator_id,
            title=title,
            description=description,
            slots=slots,
        )
        self.polls[poll_id] = poll
        self.latest_poll_by_guild[guild_id] = poll_id
        return poll

    def get_poll(self, poll_id: str) -> AvailabilityPoll | None:
        """Return a poll by id if it exists."""
        return self.polls.get(poll_id)

    def get_guild_poll(self, guild_id: int, poll_id: str) -> AvailabilityPoll | None:
        """Return a poll only if it belongs to the given guild."""
        poll = self.get_poll(poll_id)
        if poll is None or poll.guild_id != guild_id:
            return None
        return poll

    def get_latest_poll_for_guild(self, guild_id: int) -> AvailabilityPoll | None:
        """Return the most recently created poll for the guild."""
        poll_id = self.latest_poll_by_guild.get(guild_id)
        if poll_id is None:
            return None
        return self.polls.get(poll_id)

    def list_polls_for_guild(self, guild_id: int) -> list[AvailabilityPoll]:
        """Return all polls for a guild, newest first."""
        polls = [poll for poll in self.polls.values() if poll.guild_id == guild_id]
        polls.sort(key=lambda poll: poll.created_at, reverse=True)
        return polls

    def record_vote(self, poll: AvailabilityPoll, user_id: int, selections: set[int]) -> None:
        """Store the user's latest availability selections."""
        poll.votes[user_id] = selections

    def get_vote_counts(self, poll: AvailabilityPoll) -> list[int]:
        """Return vote counts aligned with the poll slots."""
        counts = [0] * len(poll.slots)
        for selections in poll.votes.values():
            for index in selections:
                if 0 <= index < len(counts):
                    counts[index] += 1
        return counts

    def get_best_slot_indexes(self, poll: AvailabilityPoll) -> list[int]:
        """Return indexes tied for the highest vote count."""
        counts = self.get_vote_counts(poll)
        if not counts:
            return []
        highest = max(counts)
        if highest == 0:
            return []
        return [index for index, count in enumerate(counts) if count == highest]

    def build_poll_embed(self, poll: AvailabilityPoll) -> discord.Embed:
        """Build a user-facing embed for an availability poll."""
        embed = discord.Embed(
            title=f"When Is Good: {poll.title}",
            description=poll.description or "Pick every time slot that works for you.",
            color=discord.Color.blue(),
            timestamp=poll.created_at,
        )
        for index, slot in enumerate(poll.slots, start=1):
            embed.add_field(name=f"Option {index}", value=slot, inline=False)
        embed.set_footer(text=f"Poll ID: {poll.poll_id}")
        return embed

    def build_results_embed(self, poll: AvailabilityPoll) -> discord.Embed:
        """Build an embed summarizing current poll results."""
        counts = self.get_vote_counts(poll)
        best_indexes = set(self.get_best_slot_indexes(poll))
        total_voters = len(poll.votes)

        embed = discord.Embed(
            title=f"Availability Results: {poll.title}",
            description=f"{total_voters} voter(s) have responded so far.",
            color=discord.Color.green(),
            timestamp=datetime.now(ZoneInfo("UTC")),
        )

        for index, slot in enumerate(poll.slots):
            prefix = "Best" if index in best_indexes else "Slot"
            embed.add_field(
                name=f"{prefix} {index + 1}",
                value=f"{slot}\nAvailable: **{counts[index]}**",
                inline=False,
            )

        if best_indexes:
            best_slots = "\n".join(poll.slots[index] for index in best_indexes)
            embed.add_field(name="Top Pick", value=best_slots, inline=False)
        else:
            embed.add_field(name="Top Pick", value="No availability has been submitted yet.", inline=False)

        embed.set_footer(text=f"Poll ID: {poll.poll_id}")
        return embed
