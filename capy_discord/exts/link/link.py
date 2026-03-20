import http.client
import logging
import urllib.error
import urllib.parse

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.embeds import error_embed, success_embed

OK_STATUS = 200


class AutoLinkCog(commands.Cog):
    """Provide a simple command for sharing a verified project link."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store bot state and the link exposed by this cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.url = "https://github.com/CAPY-RPI/discord-bot/wiki"

    def _get_status_code(self) -> int:
        """Return the HTTP status for the configured URL after scheme validation."""
        parsed_url = urllib.parse.urlparse(self.url)
        if parsed_url.scheme not in {"http", "https"}:
            msg = "Unsupported URL scheme."
            raise ValueError(msg)

        connection_class = http.client.HTTPSConnection if parsed_url.scheme == "https" else http.client.HTTPConnection
        host = parsed_url.netloc
        path = parsed_url.path or "/"
        if parsed_url.query:
            path = f"{path}?{parsed_url.query}"

        connection = connection_class(host, timeout=5)
        try:
            connection.request("HEAD", path)
            response = connection.getresponse()
            return response.status
        finally:
            connection.close()

    @app_commands.command(name="link", description="Auto-open link")
    async def link(self, interaction: discord.Interaction) -> None:
        """Send the configured link back to the user after a quick availability check."""
        try:
            status_code = self._get_status_code()

            if status_code != OK_STATUS:
                embed = error_embed("Error!", "There was a problem reaching the link.")
            else:
                embed = success_embed("Project Link", self.url)
        except (http.client.HTTPException, OSError, ValueError, urllib.error.URLError):
            embed = error_embed("Error!", "There was a problem opening the link.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Register the link cog."""
    await bot.add_cog(AutoLinkCog(bot))
