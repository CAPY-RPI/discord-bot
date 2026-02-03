"""Base class for ticket-type cogs with reaction-based status tracking."""

import logging
from typing import Any

import discord
from discord import TextChannel
from discord.ext import commands
from pydantic import BaseModel

from capy_discord.exts import tickets
from capy_discord.ui import embeds
from capy_discord.ui.views import ModalLauncherView


class TicketBase(commands.Cog):
    """Base class for ticket submission cogs."""

    def __init__(
        self,
        bot: commands.Bot,
        schema_cls: type[BaseModel],
        status_emoji: dict[str, str],
        command_config: dict[str, Any],
        reaction_footer: str,
    ) -> None:
        """Initialize the TicketBase."""
        self.bot = bot
        self.schema_cls = schema_cls
        self.status_emoji = status_emoji
        self.command_config = command_config
        self.reaction_footer = reaction_footer
        self.log = logging.getLogger(__name__)

    async def _show_feedback_button(self, interaction: discord.Interaction) -> None:
        """Show button that triggers the feedback modal."""
        view = ModalLauncherView(
            schema_cls=self.schema_cls,
            callback=self._handle_ticket_submit,
            modal_title=self.command_config["cmd_name_verbose"],
            button_label="Open Survey",
            button_emoji="📝",
            button_style=discord.ButtonStyle.success,
        )
        await view.reply(
            interaction,
            content=f"{self.command_config['cmd_emoji']} Ready to submit feedback? Click the button below!",
            ephemeral=False,
        )

    async def _validate_and_get_text_channel(self, interaction: discord.Interaction) -> TextChannel | None:
        """Validate configured channel and return it if valid."""
        channel = self.bot.get_channel(self.command_config["request_channel_id"])

        if not channel:
            self.log.error(
                "%s channel not found (ID: %s)",
                self.command_config["cmd_name_verbose"],
                self.command_config["request_channel_id"],
            )
            error_msg = (
                f"❌ **Configuration Error**\n"
                f"{self.command_config['cmd_name_verbose']} channel not configured. "
                f"Please contact an administrator."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
            return None

        if not isinstance(channel, TextChannel):
            self.log.error(
                "%s channel is not a TextChannel (ID: %s)",
                self.command_config["cmd_name_verbose"],
                self.command_config["request_channel_id"],
            )
            error_msg = (
                "❌ **Channel Error**\n"
                "The channel for receiving this type of ticket is invalid. "
                "Please contact an administrator."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
            return None

        return channel

    def _build_ticket_embed(self, data: BaseModel, submitter: discord.User | discord.Member) -> discord.Embed:
        """Build the ticket embed from validated data."""
        # Access Pydantic model fields directly
        title_value = data.title  # type: ignore[attr-defined]
        description_value = data.description  # type: ignore[attr-defined]

        embed = embeds.unmarked_embed(
            title=f"{self.command_config['cmd_name_verbose']}: {title_value}",
            description=description_value,
            emoji=self.command_config["cmd_emoji"],
        )
        embed.add_field(name="Submitted by", value=submitter.mention)

        # Build footer with status and reaction options
        footer_text = "Status: Unmarked | "
        for emoji, status in self.status_emoji.items():
            footer_text += f"{emoji} {status} • "
        footer_text = footer_text.removesuffix(" • ")

        embed.set_footer(text=footer_text)
        return embed

    async def _handle_ticket_submit(self, interaction: discord.Interaction, validated_data: BaseModel) -> None:
        """Handle ticket submission after validation."""
        # Validate channel
        channel = await self._validate_and_get_text_channel(interaction)
        if channel is None:
            return

        # Build and send embed
        embed = self._build_ticket_embed(validated_data, interaction.user)

        try:
            message = await channel.send(embed=embed)

            # Add reaction emojis
            for emoji in self.status_emoji:
                await message.add_reaction(emoji)

            # Send success message
            success_msg = f"✅ {self.command_config['cmd_name_verbose']} submitted successfully!"
            if interaction.response.is_done():
                await interaction.followup.send(success_msg, ephemeral=True)
            else:
                await interaction.response.send_message(success_msg, ephemeral=True)

            self.log.info(
                "%s '%s' submitted by user %s (ID: %s)",
                self.command_config["cmd_name_verbose"],
                validated_data.title,  # type: ignore[attr-defined]
                interaction.user,
                interaction.user.id,
            )

        except discord.HTTPException:
            self.log.exception("Failed to post ticket to channel")
            error_msg = (
                f"❌ **Submission Failed**\n"
                f"Failed to submit {self.command_config['cmd_name_verbose']}. "
                f"Please try again later."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    def _should_process_reaction(self, payload: discord.RawReactionActionEvent) -> bool:
        """Check if reaction should be processed."""
        # Only process reactions in the configured channel
        if payload.channel_id != self.command_config["request_channel_id"]:
            return False

        # Ignore bot's own reactions
        if self.bot.user and payload.user_id == self.bot.user.id:
            return False

        # Validate emoji is in status_emoji dict
        emoji = str(payload.emoji)
        return emoji in self.status_emoji

    def _is_ticket_embed(self, message: discord.Message) -> bool:
        """Check if message is a ticket embed."""
        if not message.embeds:
            return False

        title = message.embeds[0].title
        expected_prefix = f"{self.command_config['cmd_emoji']} {self.command_config['cmd_name_verbose']}:"
        return bool(title and title.startswith(expected_prefix))

    async def _update_ticket_status(
        self, message: discord.Message, emoji: str, payload: discord.RawReactionActionEvent
    ) -> None:
        """Update ticket embed with new status."""
        # Remove user's reaction (cleanup)
        if payload.member:
            try:
                await message.remove_reaction(payload.emoji, payload.member)
            except discord.HTTPException as e:
                self.log.warning("Failed to remove reaction: %s", e)

        # Update embed with new status
        embed = message.embeds[0]
        status = self.status_emoji[emoji]

        # Update color based on status using standard colors
        if status == "Unmarked":
            embed.colour = tickets.STATUS_UNMARKED
        elif status == "Acknowledged":
            embed.colour = tickets.STATUS_ACKNOWLEDGED
        elif status == "Ignored":
            embed.colour = tickets.STATUS_IGNORED

        # Update footer
        embed.set_footer(text=f"Status: {status} | {self.reaction_footer}")

        try:
            await message.edit(embed=embed)
            self.log.info("Updated ticket status to '%s' (Message ID: %s)", status, message.id)
        except discord.HTTPException as e:
            self.log.warning("Failed to update ticket embed: %s", e)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle reaction additions for status tracking."""
        if not self._should_process_reaction(payload):
            return

        # Fetch channel and message
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, TextChannel):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        except discord.HTTPException as e:
            self.log.warning("Failed to fetch message for reaction: %s", e)
            return

        # Validate it's a ticket embed
        if not self._is_ticket_embed(message):
            return

        # Update the status
        emoji = str(payload.emoji)
        await self._update_ticket_status(message, emoji, payload)
