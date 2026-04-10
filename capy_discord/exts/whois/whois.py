import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.exts.profile._schemas import UserProfileSchema
from capy_discord.ui.embeds import error_embed


class WhoIs(commands.Cog):
    """Learn about other members."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the WhoIs cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)

    @app_commands.command(name="whois", description="Find other people")
    @app_commands.describe(member="select a user to view their profile")
    async def profile(self, interaction: discord.Interaction, member: discord.Member) -> None:
        """View another user's profile."""
        profiles: dict[int, UserProfileSchema] = getattr(self.bot, "profile_store", {})
        profile = profiles.get(member.id)

        if not profile:
            embed = error_embed("Profile Not Found", f"{member.display_name} has not set up a profile yet.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = self._create_profile_embed(member, profile)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _create_profile_embed(self, member: discord.Member, profile: UserProfileSchema) -> discord.Embed:
        """Build a profile embed for the selected member."""
        embed = discord.Embed(title=f"{member.display_name}'s Profile")
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="Name", value=profile.preferred_name, inline=True)
        embed.add_field(name="Major", value=profile.major, inline=True)
        embed.add_field(name="Grad Year", value=str(profile.graduation_year), inline=True)
        embed.add_field(name="Email", value=profile.school_email, inline=True)
        embed.add_field(name="Minor", value=profile.minor or "N/A", inline=True)
        embed.add_field(name="Description", value=profile.description or "N/A", inline=False)

        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Time Viewed: {now}")
        return embed


async def setup(bot: commands.Bot) -> None:
    """Set up the Profile cog."""
    await bot.add_cog(WhoIs(bot))
