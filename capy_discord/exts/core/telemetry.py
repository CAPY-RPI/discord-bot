"""Telemetry extension for tracking Discord bot interactions.

PHASE 1: Event Capture and Logging
This is a foundational implementation that captures Discord events and logs them to console.
No database, no queue, no background tasks - just pure event capture to prove the concept works.

Key Design Decisions:
- We capture on_interaction (ALL interactions: commands, buttons, dropdowns, modals)
- We capture on_app_command (slash commands specifically with cleaner metadata)
- Data is extracted to simple dicts (not stored as Discord objects)
- All guild-specific fields handle None for DM scenarios
- Telemetry failures are caught and logged, never crashing the bot

Future Phases:
- Phase 2: Add asyncio.Queue for async event buffering
- Phase 3: Add database storage (SQLite or PostgreSQL)
- Phase 4: Add web dashboard for analytics
"""

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

# Discord component type constants
COMPONENT_TYPE_BUTTON = 2
COMPONENT_TYPE_SELECT = 3


class Telemetry(commands.Cog):
    """Telemetry Cog for capturing and logging Discord bot interactions.

    This cog listens to Discord events and extracts structured data for monitoring
    bot usage patterns, user engagement, and command popularity.

    Captured Events:
    - on_interaction: Captures ALL user interactions (commands, buttons, dropdowns, modals)
    - on_app_command: Captures slash command completions with clean metadata

    Why both events?
    - on_interaction fires BEFORE command execution (captures attempts, even failed ones)
    - on_app_command fires AFTER successful command execution (cleaner data, only successful commands)
    - Having both gives us a complete picture of user behavior
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Telemetry cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Telemetry cog initialized - Phase 1: Console logging only")

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

        Why capture this?
        - Gives us a complete picture of ALL user engagement
        - Captures failed command attempts (before validation)
        - Tracks non-command interactions (buttons, dropdowns)

        Args:
            interaction: The Discord interaction object
        """
        try:
            # Extract structured event data
            event_data = self._extract_interaction_data(interaction)

            # Log to console (Phase 1: console only, Phase 3 will add database)
            self._log_event(event_data)

        except Exception:
            # CRITICAL: Telemetry must never crash the bot
            # Log the error but don't re-raise
            self.log.exception("Failed to capture on_interaction event")

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        """Capture successful slash command executions.

        This event fires AFTER a slash command successfully completes.
        It provides cleaner metadata than on_interaction and only fires for actual commands.

        Why capture this separately from on_interaction?
        - Cleaner command metadata (name, parameters)
        - Only successful executions (on_interaction captures failed attempts too)
        - Better for analytics on "what commands users actually complete"

        Args:
            interaction: The Discord interaction object
            command: The app command that was executed
        """
        try:
            # Extract structured event data
            event_data = self._extract_app_command_data(interaction, command)

            # Log to console (Phase 1: console only)
            self._log_event(event_data)

        except Exception:
            # CRITICAL: Telemetry must never crash the bot
            self.log.exception("Failed to capture on_app_command_completion event")

    # ========================================================================================
    # DATA EXTRACTION METHODS
    # ========================================================================================

    def _extract_interaction_data(self, interaction: discord.Interaction) -> dict[str, Any]:
        """Extract structured data from a Discord interaction.

        This method converts a Discord interaction object into a simple dict
        with only the data we care about. We don't store Discord objects directly
        because they can't be serialized to JSON/database easily.

        Handles Edge Cases:
        - DMs where guild_id is None
        - Non-command interactions (buttons, dropdowns) where command name is missing
        - Complex interaction types (modals, select menus)

        Args:
            interaction: The Discord interaction object

        Returns:
            Dict with structured event data ready for logging/storage
        """
        # Determine interaction type (command, button, dropdown, modal, etc)
        interaction_type = self._get_interaction_type(interaction)

        # Extract command name if this is a command interaction
        # For buttons/dropdowns, this will be None or the custom_id
        command_name = self._get_command_name(interaction)

        # Extract command options/parameters if available
        # For slash commands: {"username": "john", "count": 5}
        # For buttons: {"custom_id": "confirm_button"}
        # For dropdowns: {"values": ["option1", "option2"]}
        options = self._extract_interaction_options(interaction)

        return {
            "event_type": "interaction",
            "interaction_type": interaction_type,
            "user_id": interaction.user.id,
            "username": str(interaction.user),  # "username#1234" or new format
            "command_name": command_name,
            "guild_id": interaction.guild_id,  # None for DMs
            "guild_name": interaction.guild.name if interaction.guild else None,
            "channel_id": interaction.channel_id,
            "timestamp": interaction.created_at,
            "options": options,
        }

    def _extract_app_command_data(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> dict[str, Any]:
        """Extract structured data from a completed app command.

        This provides cleaner metadata than on_interaction since we have
        the actual Command object with its name and parameters.

        Args:
            interaction: The Discord interaction object
            command: The app command that was executed

        Returns:
            Dict with structured event data ready for logging/storage
        """
        # Get command parameters from the interaction namespace
        # For /ping: {}
        # For /kick user:@john reason:"spam": {"user": "john", "reason": "spam"}
        options = {}
        if hasattr(interaction, "namespace"):
            # Convert namespace to dict, filtering out private attributes
            options = {
                key: self._serialize_value(value)
                for key, value in vars(interaction.namespace).items()
                if not key.startswith("_")
            }

        return {
            "event_type": "app_command",
            "command_name": command.name,
            "command_type": "context_menu" if isinstance(command, app_commands.ContextMenu) else "slash_command",
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "guild_id": interaction.guild_id,  # None for DMs
            "guild_name": interaction.guild.name if interaction.guild else None,
            "channel_id": interaction.channel_id,
            "timestamp": interaction.created_at,
            "options": options,
        }

    # ========================================================================================
    # HELPER METHODS
    # ========================================================================================

    def _get_interaction_type(self, interaction: discord.Interaction) -> str:
        """Determine the type of interaction (command, button, dropdown, modal, etc).

        Discord has many interaction types. This method converts the enum to a readable string.

        Args:
            interaction: The Discord interaction object

        Returns:
            Human-readable interaction type string
        """
        # Map Discord's InteractionType enum to readable strings
        type_map = {
            discord.InteractionType.application_command: "slash_command",
            discord.InteractionType.component: "component",  # Buttons, dropdowns
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

        For slash commands: Returns the command name (/ping -> "ping")
        For buttons/dropdowns: Returns the custom_id or None
        For modals: Returns the custom_id or None

        Args:
            interaction: The Discord interaction object

        Returns:
            Command name or custom_id, or None if not applicable
        """
        # For slash commands, use the command attribute
        if interaction.command:
            return interaction.command.name

        # For components (buttons, dropdowns) or modals, use custom_id
        if interaction.data:
            return interaction.data.get("custom_id")

        return None

    def _extract_interaction_options(self, interaction: discord.Interaction) -> dict[str, Any]:
        """Extract options/parameters from an interaction.

        Different interaction types have different data structures:
        - Slash commands: Have "options" in data
        - Buttons: Have "custom_id" in data
        - Dropdowns: Have "values" in data
        - Modals: Have "components" with field values in data

        Args:
            interaction: The Discord interaction object

        Returns:
            Dict of extracted options/data
        """
        if not interaction.data:
            return {}

        # Cast to dict to bypass TypedDict validation - Discord's interaction data
        # structure is more flexible than the typed definitions suggest
        data: dict[str, Any] = interaction.data  # type: ignore[assignment]
        options: dict[str, Any] = {}

        # Handle slash command options
        if "options" in data:
            for option in data["options"]:
                options[option["name"]] = self._serialize_value(option.get("value"))

        # Handle button custom_id
        if "custom_id" in data:
            options["custom_id"] = data["custom_id"]

        # Handle dropdown values
        if "values" in data:
            options["values"] = data["values"]

        # Handle modal components (form fields)
        if "components" in data:
            for action_row in data["components"]:
                for component in action_row.get("components", []):
                    field_id = component.get("custom_id")
                    field_value = component.get("value")
                    if field_id and field_value is not None:
                        options[field_id] = field_value

        return options

    def _serialize_value(self, value: Any) -> Any:  # noqa: ANN401
        """Convert complex Discord objects to simple serializable types.

        Discord.py uses complex objects (Member, Channel, Role, etc) that can't be
        easily logged or stored. This method converts them to simple types.

        Why we do this:
        - Easier to log to console
        - Easier to serialize to JSON
        - Easier to store in database (Phase 3)
        - Preserves only the data we actually need

        Args:
            value: Any value from Discord interaction data

        Returns:
            Serializable version of the value (int, str, list, dict)
        """
        # Discord User/Member -> user ID
        if isinstance(value, (discord.User, discord.Member)):
            return value.id

        # Discord Channel -> channel ID
        if isinstance(value, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            return value.id

        # Discord Role -> role ID
        if isinstance(value, discord.Role):
            return value.id

        # Lists (recursively serialize)
        if isinstance(value, list):
            return [self._serialize_value(v) for v in value]

        # Dicts (recursively serialize)
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}

        # Everything else (int, str, bool, None) passes through
        return value

    def _log_event(self, event_data: dict[str, Any]) -> None:
        """Log captured event data to console.

        Phase 1: Just console logging
        Phase 2: Will add to asyncio.Queue
        Phase 3: Will store in database

        Args:
            event_data: Structured event data dict
        """
        # Format timestamp for readability
        timestamp = event_data["timestamp"].strftime("%Y-%m-%d %H:%M:%S UTC")

        # Build readable log message
        event_type = event_data["event_type"]
        user_id = event_data["user_id"]
        username = event_data.get("username", "Unknown")

        if event_type == "interaction":
            interaction_type = event_data["interaction_type"]
            command_name = event_data.get("command_name", "N/A")
            guild_name = event_data.get("guild_name") or "DM"
            options = event_data.get("options", {})

            self.log.info(
                "[TELEMETRY] Interaction | Type=%s | Command=%s | User=%s(%s) | Guild=%s | Options=%s | Time=%s",
                interaction_type,
                command_name,
                username,
                user_id,
                guild_name,
                options,
                timestamp,
            )

        elif event_type == "app_command":
            command_name = event_data["command_name"]
            command_type = event_data.get("command_type", "slash_command")
            guild_name = event_data.get("guild_name") or "DM"
            options = event_data.get("options", {})

            self.log.info(
                "[TELEMETRY] AppCommand | Type=%s | Command=%s | User=%s(%s) | Guild=%s | Options=%s | Time=%s",
                command_type,
                command_name,
                username,
                user_id,
                guild_name,
                options,
                timestamp,
            )


async def setup(bot: commands.Bot) -> None:
    """Set up the Telemetry cog.

    This function is called by Discord.py's extension loader.
    It creates an instance of the Telemetry cog and adds it to the bot.

    Args:
        bot: The Discord bot instance
    """
    await bot.add_cog(Telemetry(bot))
