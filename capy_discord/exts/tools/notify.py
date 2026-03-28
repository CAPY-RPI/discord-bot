"""Safe notification command for testing the internal DM module."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.errors import UserFriendlyError
from capy_discord.services import dm, policies


class Notify(commands.Cog):
    """Cog for sending a self-targeted test DM."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Notify cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Notify cog initialized")

    @app_commands.command(name="notify", description="Send yourself a test DM")
    @app_commands.describe(message="Message content to send to your own DMs")
    @app_commands.guild_only()
    async def notify(self, interaction: discord.Interaction, message: str) -> None:
        """Send a test DM to the invoking user."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return

        policy = policies.allow_users(interaction.user.id, max_recipients=1)

        draft = await dm.compose_to_user(guild, interaction.user.id, message, policy=policy)
        self.log.debug("Notify preview\n%s", dm.render_preview(draft))

        result = await dm.send(guild, draft)
        if result.sent_count != 1:
            msg = "Failed to send test DM to the invoking user."
            raise UserFriendlyError(msg, "I couldn't DM you. Check your Discord privacy settings and try again.")

        await interaction.response.send_message("Sent you a DM.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Notify cog."""
    await bot.add_cog(Notify(bot))
