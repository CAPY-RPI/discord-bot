"""PostgreSQL queries for the event_feedback extension."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._schemas import EventFeedbackSchema, FeedbackRecord

if TYPE_CHECKING:
    import asyncpg


async def save_feedback(pool: asyncpg.Pool, record: FeedbackRecord) -> None:
    """Upsert a feedback record keyed by (guild_id, event_name, user_id)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO event_feedback
                (guild_id, event_name, user_id, display_name, rating, improvement_suggestion, anonymous)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (guild_id, event_name, user_id) DO UPDATE
                SET rating                 = EXCLUDED.rating,
                    improvement_suggestion = EXCLUDED.improvement_suggestion,
                    anonymous              = EXCLUDED.anonymous,
                    display_name           = EXCLUDED.display_name,
                    submitted_at           = NOW()
            """,
            record.guild_id,
            record.event_name,
            record.user_id,
            record.display_name,
            record.rating,
            record.improvement_suggestion,
            record.anonymous,
        )


async def get_feedback(
    pool: asyncpg.Pool,
    *,
    guild_id: int,
    event_name: str,
) -> dict[int, tuple[EventFeedbackSchema, str | None]]:
    """Return all feedback for a guild/event keyed by user_id.

    Returns:
        A dict mapping user_id -> (EventFeedbackSchema, display_name).
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, display_name, rating, improvement_suggestion, anonymous
            FROM event_feedback
            WHERE guild_id = $1 AND event_name = $2
            """,
            guild_id,
            event_name,
        )

    return {
        row["user_id"]: (
            EventFeedbackSchema(
                rating=row["rating"],
                improvement_suggestion=row["improvement_suggestion"],
                anonymous=row["anonymous"],
            ),
            row["display_name"],
        )
        for row in rows
    }


async def list_event_names(
    pool: asyncpg.Pool,
    *,
    guild_id: int,
) -> list[str]:
    """Return all event names that have feedback for a guild."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT event_name
            FROM event_feedback
            WHERE guild_id = $1
            ORDER BY event_name
            """,
            guild_id,
        )

    return [row["event_name"] for row in rows]
