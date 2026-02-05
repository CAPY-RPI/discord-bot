"""Privacy policy cog for displaying data handling information.

This module handles the display of privacy policy information to users.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands


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
            title="Privacy Policy & Data Handling",
            color=discord.Color.blue(),
            description="**Here's how we collect and handle your information:**",
        )

        embed.add_field(
            name="Basic Discord Data",
            value=("• Discord User ID\n• Server (Guild) ID\n• Channel configurations\n• Role assignments\n\n"),
            inline=False,
        )
        embed.add_field(
            name="Academic Profile Data",
            value=(
                "• Full name (first, middle, last)\n"
                "• School email address\n"
                "• Student ID number\n"
                "• Major(s)\n"
                "• Expected graduation year\n"
                "• Phone number (optional)\n\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="How We Store Your Data",
            value=("• Data is stored in a secure MongoDB database\n• Regular backups are maintained\n\n"),
            inline=False,
        )

        embed.add_field(
            name="\n",
            value=(
                "**Who can access your data:**\n"
                "• Club/Organization officers for member management\n"
                "• Server administrators for server settings\n"
                "• Bot developers for maintenance only\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="How your data is used",
            value=(
                "• Member verification and tracking\n"
                "• Event participation management\n"
                "• Academic program coordination\n"
                "• Communication within organizations\n\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="Your information is never shared or used for marketing purposes.\n", value=(""), inline=False
        )

        embed.add_field(
            name="Data Deletion",
            value=(
                "You can request data deletion through:\n"
                "• Contacting the bot administrators\n"
                "• Calling /profile delete\n\n"
                "\n"
                "Note: Some basic data may be retained for academic records as required."
            ),
            inline=False,
        )

        embed.set_footer(text="Last updated: February 2024")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Privacy cog."""
    await bot.add_cog(Privacy(bot))
