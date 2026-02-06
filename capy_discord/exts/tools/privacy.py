"""Privacy policy cog for displaying data handling information.

This module handles the display of privacy policy information to users.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

EMBED_TITLE = "Privacy Policy & Data Handling"
EMBED_DESCRIPTION = "**Here's how we collect and handle your information:**"
BASIC_DISCORD_DATA = "• Discord User ID\n• Server (Guild) ID\n• Channel configurations\n• Role assignments"
ACADEMIC_PROFILE_DATA = (
    "• Full name (first, middle, last)\n"
    "• School email address\n"
    "• Student ID number\n"
    "• Major(s)\n"
    "• Expected graduation year\n"
    "• Phone number (optional)"
)
DATA_STORAGE = "• Data is stored in a secure MongoDB database\n• Regular backups are maintained"
DATA_ACCESS = (
    "• Club/Organization officers for member management\n"
    "• Server administrators for server settings\n"
    "• Bot developers for maintenance only"
)
DATA_USAGE = (
    "• Member verification and tracking\n"
    "• Event participation management\n"
    "• Academic program coordination\n"
    "• Communication within organizations"
)
DATA_SHARING = "**Your information is never shared with third parties or used for marketing purposes.**"
DATA_DELETION = (
    "You can request data deletion through:\n"
    "• Contacting the bot administrators\n"
    "• Calling /profile delete\n\n"
    f"{DATA_SHARING}\n\n"
    "Note: Some basic data may be retained for academic records as required."
)
FOOTER_TEXT = "Last updated: February 2026"


class Privacy(commands.Cog):
    """Privacy policy and data handling information cog."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Privacy cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.log.info("Privacy cog initialized")

    @app_commands.command(
        name="privacy",
        description="View our privacy policy and data handling practices",
    )
    async def privacy(self, interaction: discord.Interaction) -> None:
        """Display privacy policy and data handling information.

        Args:
            interaction: The Discord interaction initiating the command
        """
        embed = discord.Embed(
            title=EMBED_TITLE,
            color=discord.Color.blue(),
            description=EMBED_DESCRIPTION,
        )

        embed.add_field(
            name="Basic Discord Data",
            value=BASIC_DISCORD_DATA,
            inline=False,
        )
        embed.add_field(
            name="Academic Profile Data",
            value=ACADEMIC_PROFILE_DATA,
            inline=False,
        )

        embed.add_field(
            name="How We Store Your Data",
            value=DATA_STORAGE,
            inline=False,
        )

        embed.add_field(
            name="Who Can Access Your Data",
            value=DATA_ACCESS,
            inline=False,
        )
        embed.add_field(
            name="How Your Data Is Used",
            value=DATA_USAGE,
            inline=False,
        )

        embed.add_field(
            name="Data Deletion",
            value=DATA_DELETION,
            inline=False,
        )

        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Privacy cog."""
    await bot.add_cog(Privacy(bot))
