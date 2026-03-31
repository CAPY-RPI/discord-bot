import logging

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.embeds import error_embed

from ._profiles import create_profile_embed, get_profile_store


class Member(commands.GroupCog, group_name="member", group_description="View member profiles"):
    """Member discovery commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the member command group."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.profiles = get_profile_store(bot)

    @app_commands.command(name="view", description="View another member's profile")
    @app_commands.describe(member="Select a user to view their profile")
    async def view(self, interaction: discord.Interaction, member: discord.Member) -> None:
        """Show the selected member's profile if one exists."""
        profile = self.profiles.get(member.id)

        if not profile:
            embed = error_embed("Profile Not Found", f"{member.display_name} has not set up a profile yet.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = create_profile_embed(member, profile)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Register the member cog."""
    await bot.add_cog(Member(bot))
