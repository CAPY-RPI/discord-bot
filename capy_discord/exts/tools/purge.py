import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class DateTimeModal(discord.ui.Modal):
    """Modal for date and time input."""

    def __init__(self) -> None:
        """Initialize the date time modal."""
        super().__init__(title="Enter Date and Time")
        self.add_item(
            discord.ui.TextInput(
                label="Date (YYYY-MM-DD)",
                placeholder="2024-02-08",
                required=True,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                label="Time (HH:MM)",
                placeholder="14:30",
                required=True,
            )
        )


class PurgeModeView(discord.ui.View):
    """Modal for Menu View."""

    def __init__(self) -> None:
        """Initialize the Menu View."""
        super().__init__()
        self.mode: str | None = None
        self.value: int | str | datetime | None = None
        self.mode_select: discord.ui.Select[discord.ui.View] = discord.ui.Select(
            placeholder="Choose purge mode",
            options=[
                discord.SelectOption(
                    label="Message Count",
                    value="count",
                    description="Delete specific number of messages",
                ),
                discord.SelectOption(
                    label="Time Duration",
                    value="duration",
                    description="Delete messages from last X time",
                ),
                discord.SelectOption(
                    label="Specific Date",
                    value="date",
                    description="Delete messages since specific date/time",
                ),
            ],
        )

        self.mode_select.callback = self.on_mode_selected  # type: ignore[method-assign]
        self.add_item(self.mode_select)

    async def _prompt_count(self, interaction: discord.Interaction) -> None:
        modal = discord.ui.Modal(title="Enter Count")
        text_input: Any = discord.ui.TextInput(label="Number of messages", placeholder="10")
        modal.add_item(text_input)

        async def _on_submit(_: discord.Interaction) -> None:
            try:
                self.value = int(text_input.value)
                await _.response.defer()
                self.stop()
            except ValueError:
                await _.response.send_message("Please enter a valid integer.", ephemeral=True)

        cast("Any", modal).on_submit = _on_submit
        await interaction.response.send_modal(modal)

    async def _prompt_duration(self, interaction: discord.Interaction) -> None:
        modal = discord.ui.Modal(title="Enter Duration")
        text_input: Any = discord.ui.TextInput(
            label="Duration (1d2h3m)",
            placeholder="1d = 1 day, 2h = 2 hours, 3m = 3 minutes",
        )
        modal.add_item(text_input)

        async def _on_submit(_: discord.Interaction) -> None:
            self.value = text_input.value
            await _.response.defer()
            self.stop()

        cast("Any", modal).on_submit = _on_submit
        await interaction.response.send_modal(modal)

    async def _prompt_date(self, interaction: discord.Interaction) -> None:
        modal = DateTimeModal()

        async def _on_submit(_: discord.Interaction) -> None:
            try:
                date_input = modal.children[0]
                time_input = modal.children[1]
                if isinstance(date_input, discord.ui.TextInput) and isinstance(time_input, discord.ui.TextInput):
                    y, m, d = map(int, date_input.value.split("-"))
                    hh, mm = map(int, time_input.value.split(":"))
                    self.value = datetime(y, m, d, hh, mm, tzinfo=UTC)
                await _.response.defer()
                self.stop()
            except ValueError:
                await _.response.send_message("Invalid date/time format", ephemeral=True)

        cast("Any", modal).on_submit = _on_submit  # type: ignore[method-assign]
        await interaction.response.send_modal(modal)

    async def on_mode_selected(self, interaction: discord.Interaction) -> None:
        """Handle the user's selected purge mode and prompt for parameters."""
        if not self.mode_select.values:
            await interaction.response.send_message("No mode selected.", ephemeral=True)
            return

        mode = self.mode_select.values[0]
        self.mode = mode

        handlers: dict[str, Callable[[discord.Interaction], Awaitable[None]]] = {
            "count": self._prompt_count,
            "duration": self._prompt_duration,
            "date": self._prompt_date,
        }
        handler = handlers.get(mode)
        if handler:
            await handler(interaction)
        else:
            await interaction.response.send_message("Invalid mode selected.", ephemeral=True)


class PurgeCog(commands.Cog):
    """Cog for delete messages permanently based on mode."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the purge cog."""
        self.bot = bot
        self.logger = logging.getLogger(f"discord.cog.{self.__class__.__name__.lower()}")

    def parse_duration(self, duration: str) -> timedelta | None:
        """Parse duration string into timedelta. Format: 1d2h3m."""
        if not duration:
            return None

        pattern = r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?"
        match = re.match(pattern, duration)
        if not match or not any(match.groups()):
            return None

        days = int(match.group(1) or 0)
        hours = int(match.group(2) or 0)
        minutes = int(match.group(3) or 0)

        return timedelta(days=days, hours=hours, minutes=minutes)

    async def _handle_purge_count(self, amount: int, channel: discord.TextChannel) -> tuple[bool, str]:
        if amount <= 0:
            return False, "Please specify a number greater than 0"
        deleted = await channel.purge(limit=amount)
        return True, f"✨ Successfully deleted {len(deleted)} messages!"

    async def _handle_purge_duration(self, duration: str, channel: discord.TextChannel) -> tuple[bool, str]:
        time_delta = self.parse_duration(duration)
        if not time_delta:
            return (
                False,
                "Invalid duration format. Use format: 1d2h3m (e.g., 1d = 1 day,2h = 2 hours, 3m = 3 minutes)",
            )

        after_time = datetime.now(UTC) - time_delta
        deleted = await channel.purge(after=after_time)
        return (
            True,
            f"✨ Successfully deleted {len(deleted)} messages from the last {duration}!",
        )

    async def _handle_purge_date(self, date: datetime, channel: discord.TextChannel) -> tuple[bool, str]:
        if date > datetime.now(UTC):
            return False, "Cannot purge future messages"
        deleted = await channel.purge(after=date)
        date_str = date.strftime("%Y-%m-%d %H:%M")
        return (
            True,
            f"✨ Successfully deleted {len(deleted)} messages since {date_str}!",
        )

    @app_commands.command(name="purge", description="Delete messages")
    @app_commands.describe(
        amount="The number of messages to delete (e.g. 10)",
        duration="The timeframe to delete messages from (e.g. 1h 30m)",
    )
    # @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self, interaction: discord.Interaction, amount: int | None = None, duration: str | None = None
    ) -> None:
        """Purge method with view and execution."""
        if amount is not None and duration is not None:
            await interaction.response.send_message(
                "❌ Please provide **either** an amount **or** a duration, not both.", ephemeral=True
            )
            return
        if amount is not None:
            channel = interaction.channel
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message(
                    "This command can only be used in text channels.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            success, message = await self._handle_purge_count(amount, channel)
            await interaction.followup.send(message, ephemeral=True)
            return
        if duration is not None:
            channel = interaction.channel
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message(
                    "This command can only be used in text channels.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            success, message = await self._handle_purge_duration(duration, channel)
            await interaction.followup.send(message, ephemeral=True)
            return

        view = PurgeModeView()
        await interaction.response.send_message("Select purge mode:", view=view, ephemeral=True)

        await view.wait()
        if not view.mode or not view.value:
            await interaction.followup.send("Purge cancelled or timed out.", ephemeral=True)
            return

        try:
            success, message = await self._execute_purge(view, interaction.channel)
            await interaction.followup.send(f"Success {message}", ephemeral=True)
            if success:
                self.logger.info(f"{interaction.user} purged messages in {interaction.channel} using {view.mode} mode")
        except discord.Forbidden:
            await interaction.followup.send("Error, I don't have permission to delete messages", ephemeral=True)
        except Exception:
            await interaction.followup.send("Error, An error occurred: ", ephemeral=True)

    async def _execute_purge(
        self,
        view: PurgeModeView,
        channel: discord.abc.GuildChannel | discord.abc.PrivateChannel | discord.Thread | None,
    ) -> tuple[bool, str]:
        """Execute purge action based on selected mode."""
        if channel is None:
            return False, "This command must be used in a channel."
        if not isinstance(channel, discord.TextChannel):
            return False, "This command can only be used in text channels."

        if view.mode == "count" and isinstance(view.value, int):
            return await self._handle_purge_count(view.value, channel)
        if view.mode == "duration" and isinstance(view.value, str):
            return await self._handle_purge_duration(view.value, channel)
        if view.mode == "date" and isinstance(view.value, datetime):
            return await self._handle_purge_date(view.value, channel)

        return False, "Invalid mode/value combination. Please try again."


async def setup(bot: commands.Bot) -> None:
    """Set up the Sync cog."""
    await bot.add_cog(PurgeCog(bot))
