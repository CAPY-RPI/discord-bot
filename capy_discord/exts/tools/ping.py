import discord
from discord import app_commands
from discord.ext import commands

import capy_discord
from capy_discord.logging import get_logger


class Ping(commands.Cog):
    """Cog for ping command."""

    def __init__(self) -> None:
        """Initialize the Ping cog."""
        self.logger = get_logger(__name__)

    @app_commands.command(name="ping", description="Shows the bot's latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Respond with the bot's latency."""
        try:
            latency = round(capy_discord.instance.latency * 1000)  # in ms
            message = f"Pong! {latency} ms Latency!"
            embed = discord.Embed(title="Ping", description=message)
            self.logger.info("/ping invoked user: %s guild: %s", interaction.user.id, interaction.guild_id)

            await interaction.response.send_message(embed=embed)

        except Exception:
            self.logger.exception("/ping attempted user")
            await interaction.response.send_message("We're sorry, this interaction failed. Please contact an admin.")


async def setup(bot: commands.Bot) -> None:
    """Set up the Ping cog."""
    await bot.add_cog(Ping())
