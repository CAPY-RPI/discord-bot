import asyncio
from unittest.mock import MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from capy_discord.errors import UserFriendlyError
from capy_discord.exts.core.telemetry import (
    Telemetry,
    TelemetryEvent,
    _QUEUE_MAX_SIZE,
)


@pytest.fixture
def bot():
    intents = discord.Intents.default()
    b = MagicMock(spec=commands.Bot)
    b.intents = intents
    b.wait_until_ready = MagicMock(return_value=asyncio.Future())
    b.wait_until_ready.return_value.set_result(None)
    return b


@pytest.fixture
def cog(bot):
    with patch.object(Telemetry, "cog_load", return_value=None):
        c = Telemetry(bot)
    c.log = MagicMock()
    return c


def _make_interaction(*, interaction_id=12345, command_name="test_cmd"):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.id = interaction_id
    interaction.type = discord.InteractionType.application_command
    interaction.user = MagicMock()
    interaction.user.id = 99
    interaction.user.__str__ = MagicMock(return_value="TestUser#0001")
    interaction.guild_id = 1
    interaction.guild = MagicMock()
    interaction.guild.name = "TestGuild"
    interaction.channel_id = 2
    interaction.created_at = MagicMock()
    interaction.created_at.strftime = MagicMock(return_value="2025-01-01 00:00:00 UTC")
    interaction.command = MagicMock()
    interaction.command.name = command_name
    interaction.data = {"name": command_name}
    return interaction


@pytest.mark.asyncio
async def test_interaction_event_enqueued(cog):
    interaction = _make_interaction()

    await cog.on_interaction(interaction)

    assert cog._queue.qsize() == 1
    event = cog._queue.get_nowait()
    assert event.event_type == "interaction"
    assert event.data["command_name"] == "test_cmd"
    assert "correlation_id" in event.data


@pytest.mark.asyncio
async def test_completion_event_enqueued(cog):
    interaction = _make_interaction()
    command = MagicMock(spec=app_commands.Command)
    command.name = "ping"

    # Seed _pending so completion can find it
    cog._pending[interaction.id] = ("abc123", 0.0)

    await cog.on_app_command_completion(interaction, command)

    assert cog._queue.qsize() == 1
    event = cog._queue.get_nowait()
    assert event.event_type == "completion"
    assert event.data["status"] == "success"
    assert event.data["command_name"] == "ping"


@pytest.mark.asyncio
async def test_failure_user_error_categorized(cog):
    interaction = _make_interaction()
    cog._pending[interaction.id] = ("abc123", 0.0)

    user_err = UserFriendlyError("internal msg", "user msg")
    wrapped = app_commands.CommandInvokeError(MagicMock(), user_err)

    cog.log_command_failure(interaction, wrapped)

    event = cog._queue.get_nowait()
    assert event.data["status"] == "user_error"
    assert event.data["error_type"] == "UserFriendlyError"


@pytest.mark.asyncio
async def test_failure_internal_error_categorized(cog):
    interaction = _make_interaction()
    cog._pending[interaction.id] = ("abc123", 0.0)

    internal_err = RuntimeError("something broke")
    wrapped = app_commands.CommandInvokeError(MagicMock(), internal_err)

    cog.log_command_failure(interaction, wrapped)

    event = cog._queue.get_nowait()
    assert event.data["status"] == "internal_error"
    assert event.data["error_type"] == "RuntimeError"


def test_queue_full_drops_event(cog):
    # Fill the queue to capacity
    for i in range(_QUEUE_MAX_SIZE):
        cog._queue.put_nowait(TelemetryEvent("interaction", {"i": i}))

    assert cog._queue.full()

    # This should not raise — it logs a warning and drops the event
    cog._enqueue(TelemetryEvent("interaction", {"dropped": True}))

    cog.log.warning.assert_called_once()
    assert "queue full" in cog.log.warning.call_args[0][0].lower()


def test_consumer_processes_events(cog):
    events_to_process = 2
    cog._queue.put_nowait(
        TelemetryEvent(
            "completion",
            {
                "correlation_id": "abc",
                "command_name": "ping",
                "status": "success",
                "duration_ms": 5.0,
            },
        )
    )
    cog._queue.put_nowait(
        TelemetryEvent(
            "completion",
            {
                "correlation_id": "def",
                "command_name": "help",
                "status": "success",
                "duration_ms": 3.0,
            },
        )
    )

    cog._process_pending_events()

    assert cog._queue.qsize() == 0
    assert cog.log.debug.call_count == events_to_process


def test_drain_on_unload(cog):
    cog._queue.put_nowait(
        TelemetryEvent(
            "completion",
            {
                "correlation_id": "abc",
                "command_name": "ping",
                "status": "success",
                "duration_ms": 1.0,
            },
        )
    )

    cog._drain_queue()

    assert cog._queue.qsize() == 0
    # Should have logged the completion + a warning about draining
    cog.log.warning.assert_called_once()
    assert "Drained" in cog.log.warning.call_args[0][0]


def test_dispatch_unknown_event_type(cog):
    cog._dispatch_event(TelemetryEvent("bogus_type", {}))

    cog.log.warning.assert_called_once()
    assert "Unknown telemetry event type" in cog.log.warning.call_args[0][0]
