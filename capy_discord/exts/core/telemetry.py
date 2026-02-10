"""Telemetry extension for tracking Discord bot interactions.

PHASE 2a: Queue Buffering and Error Categorization
Builds on Phase 1 event capture by adding:
- asyncio.Queue to decouple event listeners from I/O (fire-and-forget enqueue)
- Background consumer task that drains the queue and logs events
- Error categorization: "user_error" (UserFriendlyError) vs "internal_error" (real bugs)

Key Design Decisions:
- We capture on_interaction (ALL interactions: commands, buttons, dropdowns, modals)
- We capture on_app_command (slash commands specifically with cleaner metadata)
- Data is extracted to simple dicts (not stored as Discord objects)
- All guild-specific fields handle None for DM scenarios
- Telemetry failures are caught and logged, never crashing the bot
- Each interaction gets a UUID correlation_id linking interaction and completion logs
- Command failures are tracked via log_command_failure called from bot error handlers

Future Phases:
- Phase 3: Add database storage (SQLite or PostgreSQL)
- Phase 4: Add web dashboard for analytics
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from capy_discord.errors import UserFriendlyError

# Discord component type constants
COMPONENT_TYPE_BUTTON = 2
COMPONENT_TYPE_SELECT = 3

# Stale interaction entries older than this (seconds) are cleaned up
_STALE_THRESHOLD_SECONDS = 60

# Queue and consumer configuration
_QUEUE_MAX_SIZE = 1000
_CONSUMER_INTERVAL_SECONDS = 1.0


@dataclass(slots=True)
class TelemetryEvent:
    """A telemetry event to be processed by the background consumer."""

    event_type: str  # "interaction" or "completion"
    data: dict[str, Any]


class Telemetry(commands.Cog):
    """Telemetry Cog for capturing and logging Discord bot interactions.

    This cog listens to Discord events and extracts structured data for monitoring
    bot usage patterns, user engagement, and command popularity.

    Captured Events:
    - on_interaction: Captures ALL user interactions (commands, buttons, dropdowns, modals)
    - on_app_command_completion: Captures slash command completions with clean metadata
    - log_command_failure: Called from bot error handler to capture failed commands

    Each interaction is assigned a UUID correlation_id that links the interaction log
    to its corresponding completion or failure log.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Telemetry cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self.log = logging.getLogger(__name__)
        # Maps interaction.id -> (correlation_id, start_time_monotonic)
        self._pending: dict[int, tuple[str, float]] = {}
        self._queue: asyncio.Queue[TelemetryEvent] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self.log.info("Telemetry cog initialized - Phase 2a: Queue buffering and error categorization")

    # ========================================================================================
    # LIFECYCLE
    # ========================================================================================

    async def cog_load(self) -> None:
        """Start the background consumer task."""
        self._consumer_task.start()

    async def cog_unload(self) -> None:
        """Stop the consumer and flush remaining events."""
        self._consumer_task.cancel()
        self._drain_queue()

    # ========================================================================================
    # BACKGROUND CONSUMER
    # ========================================================================================

    @tasks.loop(seconds=_CONSUMER_INTERVAL_SECONDS)
    async def _consumer_task(self) -> None:
        """Periodically drain the queue and process pending telemetry events."""
        self._process_pending_events()

    @_consumer_task.before_loop
    async def _before_consumer(self) -> None:
        await self.bot.wait_until_ready()

    def _process_pending_events(self) -> None:
        """Drain the queue and dispatch each event. Capped at _QUEUE_MAX_SIZE per tick."""
        processed = 0
        while processed < _QUEUE_MAX_SIZE:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._dispatch_event(event)
            processed += 1

    def _drain_queue(self) -> None:
        """Flush remaining events on unload. Warns if any events were pending."""
        count = 0
        while True:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._dispatch_event(event)
            count += 1
        if count:
            self.log.warning("Drained %d telemetry event(s) during cog unload", count)

    def _dispatch_event(self, event: TelemetryEvent) -> None:
        """Route an event to the appropriate logging method.

        Args:
            event: The telemetry event to dispatch
        """
        try:
            if event.event_type == "interaction":
                self._log_interaction(event.data)
            elif event.event_type == "completion":
                self._log_completion(**event.data)
            else:
                self.log.warning("Unknown telemetry event type: %s", event.event_type)
        except Exception:
            self.log.exception("Failed to dispatch telemetry event: %s", event.event_type)

    def _enqueue(self, event: TelemetryEvent) -> None:
        """Enqueue a telemetry event. Drops the event if the queue is full.

        Args:
            event: The telemetry event to enqueue
        """
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.log.warning("Telemetry queue full — dropping %s event", event.event_type)

    # ========================================================================================
    # EVENT LISTENERS
    # ========================================================================================

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Capture ALL interactions (commands, buttons, dropdowns, modals, etc).

        This event fires for EVERY user interaction with the bot, including:
        - Slash commands (/ping, /feedback, etc)
        - Button clicks (Confirm, Cancel, etc)
        - Dropdown selections (Select menus)
        - Modal submissions (Forms)

        Args:
            interaction: The Discord interaction object
        """
        try:
            # Clean up stale entries that never got a completion/failure
            self._cleanup_stale_entries()

            # Generate correlation ID and record start time
            correlation_id = uuid.uuid4().hex[:12]
            self._pending[interaction.id] = (correlation_id, time.monotonic())

            # Extract structured event data
            event_data = self._extract_interaction_data(interaction)
            event_data["correlation_id"] = correlation_id

            # Enqueue for background processing
            self._enqueue(TelemetryEvent("interaction", event_data))

        except Exception:
            # CRITICAL: Telemetry must never crash the bot
            self.log.exception("Failed to capture on_interaction event")

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        """Capture successful slash command executions.

        Logs a slim completion record with correlation_id, command name,
        status, and execution time. Full metadata is in the interaction log.

        Args:
            interaction: The Discord interaction object
            command: The app command that was executed
        """
        try:
            correlation_id, start_time = self._pop_pending(interaction.id)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)

            self._enqueue(
                TelemetryEvent(
                    "completion",
                    {
                        "correlation_id": correlation_id,
                        "command_name": command.name,
                        "status": "success",
                        "duration_ms": duration_ms,
                    },
                )
            )

        except Exception:
            # CRITICAL: Telemetry must never crash the bot
            self.log.exception("Failed to capture on_app_command_completion event")

    # ========================================================================================
    # FAILURE TRACKING (called from bot.py error handler)
    # ========================================================================================

    def log_command_failure(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Log a command failure with correlation to the original interaction.

        Called from Bot.on_tree_error to track which commands fail and why.
        Categorizes errors as "user_error" (UserFriendlyError) or "internal_error".

        Args:
            interaction: The Discord interaction object
            error: The error that occurred
        """
        try:
            correlation_id, start_time = self._pop_pending(interaction.id)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)

            # Unwrap CommandInvokeError to get the actual cause
            actual_error = error.original if isinstance(error, app_commands.CommandInvokeError) else error

            status = "user_error" if isinstance(actual_error, UserFriendlyError) else "internal_error"

            error_type = type(actual_error).__name__

            self._enqueue(
                TelemetryEvent(
                    "completion",
                    {
                        "correlation_id": correlation_id,
                        "command_name": interaction.command.name if interaction.command else "unknown",
                        "status": status,
                        "duration_ms": duration_ms,
                        "error_type": error_type,
                    },
                )
            )

        except Exception:
            self.log.exception("Failed to capture command failure event")

    # ========================================================================================
    # DATA EXTRACTION METHODS
    # ========================================================================================

    def _extract_interaction_data(self, interaction: discord.Interaction) -> dict[str, Any]:
        """Extract structured data from a Discord interaction.

        This method converts a Discord interaction object into a simple dict
        with only the data we care about. We don't store Discord objects directly
        because they can't be serialized to JSON/database easily.

        Args:
            interaction: The Discord interaction object

        Returns:
            Dict with structured event data ready for logging/storage
        """
        interaction_type = self._get_interaction_type(interaction)
        command_name = self._get_command_name(interaction)
        options = self._extract_interaction_options(interaction)

        return {
            "event_type": "interaction",
            "interaction_type": interaction_type,
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "command_name": command_name,
            "guild_id": interaction.guild_id,
            "guild_name": interaction.guild.name if interaction.guild else None,
            "channel_id": interaction.channel_id,
            "timestamp": interaction.created_at,
            "options": options,
        }

    # ========================================================================================
    # HELPER METHODS
    # ========================================================================================

    def _pop_pending(self, interaction_id: int) -> tuple[str, float]:
        """Pop and return the pending entry for an interaction.

        If the entry doesn't exist (e.g. race condition or missed event),
        returns a fallback with current time.

        Args:
            interaction_id: Discord interaction snowflake ID

        Returns:
            Tuple of (correlation_id, start_time)
        """
        if interaction_id in self._pending:
            return self._pending.pop(interaction_id)
        return ("unknown", time.monotonic())

    def _cleanup_stale_entries(self) -> None:
        """Remove pending entries older than the stale threshold.

        Prevents memory leaks from interactions that never get a
        completion or failure callback.
        """
        now = time.monotonic()
        stale_ids = [
            iid for iid, (_, start_time) in self._pending.items() if now - start_time > _STALE_THRESHOLD_SECONDS
        ]
        for iid in stale_ids:
            del self._pending[iid]

    def _get_interaction_type(self, interaction: discord.Interaction) -> str:
        """Determine the type of interaction (command, button, dropdown, modal, etc).

        Args:
            interaction: The Discord interaction object

        Returns:
            Human-readable interaction type string
        """
        type_map = {
            discord.InteractionType.application_command: "slash_command",
            discord.InteractionType.component: "component",
            discord.InteractionType.modal_submit: "modal",
            discord.InteractionType.autocomplete: "autocomplete",
        }

        interaction_type = type_map.get(interaction.type, "unknown")

        # For component interactions, get more specific type
        if interaction_type == "component" and interaction.data:
            component_type = interaction.data.get("component_type")
            if component_type == COMPONENT_TYPE_BUTTON:
                interaction_type = "button"
            elif component_type == COMPONENT_TYPE_SELECT:
                interaction_type = "dropdown"

        return interaction_type

    def _get_command_name(self, interaction: discord.Interaction) -> str | None:
        """Extract the command name from an interaction.

        Args:
            interaction: The Discord interaction object

        Returns:
            Command name or custom_id, or None if not applicable
        """
        if interaction.command:
            return interaction.command.name

        if interaction.data:
            return interaction.data.get("custom_id")

        return None

    def _extract_interaction_options(self, interaction: discord.Interaction) -> dict[str, Any]:
        """Extract options/parameters from an interaction.

        Args:
            interaction: The Discord interaction object

        Returns:
            Dict of extracted options/data
        """
        if not interaction.data:
            return {}

        data: dict[str, Any] = interaction.data  # type: ignore[assignment]
        options: dict[str, Any] = {}

        if "options" in data:
            self._extract_command_options(data["options"], options)

        if "custom_id" in data:
            options["custom_id"] = data["custom_id"]

        if "values" in data:
            options["values"] = data["values"]

        if "components" in data:
            self._extract_modal_components(data["components"], options)

        return options

    def _extract_command_options(
        self, option_list: list[dict[str, Any]], options: dict[str, Any], prefix: str = ""
    ) -> None:
        """Recursively extract and flatten slash command options.

        Args:
            option_list: List of command options from interaction data
            options: Dictionary to populate with flattened options (modified in place)
            prefix: Current prefix for nested options (e.g., "subcommand")
        """
        for opt in option_list:
            name = opt.get("name")
            if not name:
                continue

            full_name = f"{prefix}.{name}" if prefix else name

            if "options" in opt and isinstance(opt["options"], list):
                self._extract_command_options(opt["options"], options, full_name)
            elif "value" in opt:
                options[full_name] = self._serialize_value(opt.get("value"))

    def _extract_modal_components(self, components: list[dict[str, Any]], options: dict[str, Any]) -> None:
        """Extract form field values from modal components.

        Args:
            components: List of modal components (action rows)
            options: Dictionary to populate with field values (modified in place)
        """
        for action_row in components:
            for component in action_row.get("components", []):
                field_id = component.get("custom_id")
                field_value = component.get("value")
                if field_id and field_value is not None:
                    options[field_id] = field_value

    def _serialize_value(self, value: Any) -> Any:  # noqa: ANN401
        """Convert complex Discord objects to simple serializable types.

        Args:
            value: Any value from Discord interaction data

        Returns:
            Serializable version of the value (int, str, list, dict)
        """
        if isinstance(value, (discord.User, discord.Member)):
            return value.id

        if isinstance(value, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            return value.id

        if isinstance(value, discord.Role):
            return value.id

        if isinstance(value, list):
            return [self._serialize_value(v) for v in value]

        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}

        return value

    # ========================================================================================
    # LOGGING METHODS
    # ========================================================================================

    def _log_interaction(self, event_data: dict[str, Any]) -> None:
        """Log the full interaction event at DEBUG level.

        Contains all metadata for the interaction. The completion/failure log
        references this via correlation_id.

        Args:
            event_data: Structured event data dict
        """
        timestamp = event_data["timestamp"].strftime("%Y-%m-%d %H:%M:%S UTC")
        correlation_id = event_data["correlation_id"]
        interaction_type = event_data["interaction_type"]
        command_name = event_data.get("command_name", "N/A")
        username = event_data.get("username", "Unknown")
        user_id = event_data["user_id"]
        guild_name = event_data.get("guild_name") or "DM"
        options = event_data.get("options", {})

        self.log.debug(
            "[TELEMETRY] Interaction | ID=%s | Type=%s | Command=%s | User=%s(%s) | Guild=%s | Options=%s | Time=%s",
            correlation_id,
            interaction_type,
            command_name,
            username,
            user_id,
            guild_name,
            options,
            timestamp,
        )

    def _log_completion(
        self,
        *,
        correlation_id: str,
        command_name: str,
        status: str,
        duration_ms: float,
        error_type: str | None = None,
    ) -> None:
        """Log a slim completion/failure record at DEBUG level.

        Only contains correlation_id, command name, status, duration, and
        optionally error type. Full metadata lives in the interaction log.

        Args:
            correlation_id: UUID linking to the interaction log
            command_name: The command that completed/failed
            status: "success", "user_error", or "internal_error"
            duration_ms: Execution time in milliseconds
            error_type: Error class name (only for failures)
        """
        if error_type:
            self.log.debug(
                "[TELEMETRY] Completion | ID=%s | Command=%s | Status=%s | Error=%s | Duration=%sms",
                correlation_id,
                command_name,
                status,
                error_type,
                duration_ms,
            )
        else:
            self.log.debug(
                "[TELEMETRY] Completion | ID=%s | Command=%s | Status=%s | Duration=%sms",
                correlation_id,
                command_name,
                status,
                duration_ms,
            )


async def setup(bot: commands.Bot) -> None:
    """Set up the Telemetry cog.

    This function is called by Discord.py's extension loader.
    It creates an instance of the Telemetry cog and adds it to the bot.

    Args:
        bot: The Discord bot instance
    """
    await bot.add_cog(Telemetry(bot))
