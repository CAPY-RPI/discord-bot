import discord
from discord import app_commands
from discord.ext import commands

import capy_discord


class PingCog(commands.Cog):
    """Cog for ping command."""

    @app_commands.command(name="ping", description="Shows the bot's latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Respond with the bot's latency."""
        message = f"⏱ {round(capy_discord.instance.latency * 1000)} ms Latency!"
        embed = discord.Embed(title="Ping", description=message)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    """Set up the Ping cog."""
    await bot.add_cog(PingCog())
