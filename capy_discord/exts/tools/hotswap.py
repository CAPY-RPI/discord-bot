import logging
from typing import Literal

import discord
from discord import app_commands, ui
from discord.ext import commands
from discord.ext.commands import AutoShardedBot, Bot

from capy_discord.config import settings
from capy_discord.ui.embeds import error_embed, success_embed
from capy_discord.ui.views import BaseView
from capy_discord.utils.extensions import walk_extensions

log = logging.getLogger(__name__)


class HotswapSelect(ui.Select):
    """Dropdown for selecting extensions to hotswap."""

    def __init__(self, extensions: list[str], action: str) -> None:
        """Initialize the HotswapSelect dropdown."""
        self.action = action
        options = [discord.SelectOption(label=ext, value=ext) for ext in extensions]
        super().__init__(
            placeholder=f"Select an extension to {action}...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle the selection and perform the requested action."""
        cog_name = self.values[0]
        bot = interaction.client

        if not isinstance(bot, (Bot, AutoShardedBot)):
            log.error("Interaction client is not a Bot or AutoShardedBot instance.")
            return

        try:
            if self.action == "reload":
                await bot.reload_extension(cog_name)
            elif self.action == "load":
                await bot.load_extension(cog_name)
            elif self.action == "unload":
                await bot.unload_extension(cog_name)

            await interaction.response.send_message(
                embed=success_embed(
                    f"Extension {self.action.capitalize()}ed",
                    f"Successfully {self.action}ed `{cog_name}`.",
                ),
                ephemeral=True,
            )
        except Exception as e:
            log.exception("Failed to %s extension %s", self.action, cog_name)
            await interaction.response.send_message(
                embed=error_embed(
                    f"Failed to {self.action.capitalize()} Extension",
                    f"An error occurred while {self.action}ing `{cog_name}`: `{e}`",
                ),
                ephemeral=True,
            )


class HotswapView(BaseView):
    """View for hotswapping extensions."""

    def __init__(self, extensions: list[str], action: str, *, timeout: float | None = 180) -> None:
        """Initialize the HotswapView."""
        super().__init__(timeout=timeout)
        self.add_item(HotswapSelect(extensions, action))


class HotswapCog(commands.Cog):
    """Cog for reloading, loading, and unloading extensions at runtime."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the HotswapCog."""
        self.bot = bot

    def get_unloaded_cogs(self) -> list[str]:
        """Get a list of cogs that are currently not loaded."""
        all_extensions = set(walk_extensions())
        loaded_extensions = set(self.bot.extensions.keys())
        return sorted(all_extensions - loaded_extensions)

    @app_commands.command(name="hotswap", description="Reload, load, or unload bot extensions.")
    @app_commands.describe(action="The action to perform")
    @app_commands.checks.has_permissions(administrator=True)
    async def hotswap(
        self,
        interaction: discord.Interaction,
        action: Literal["reload", "load", "unload"],
    ) -> None:
        """Handle the /hotswap command."""
        if action == "reload":
            # Prevent self-reload to avoid potentially breaking the hotswap command during use
            extensions = [ext for ext in self.bot.extensions if ext != "capy_discord.exts.tools.hotswap"]
            if not extensions:
                await interaction.response.send_message("No extensions are currently loaded.", ephemeral=True)
                return
        elif action == "load":
            extensions = self.get_unloaded_cogs()
            if not extensions:
                await interaction.response.send_message("All available extensions are already loaded.", ephemeral=True)
                return
        else:  # unload
            extensions = [ext for ext in self.bot.extensions if ext != "capy_discord.exts.tools.hotswap"]
            if not extensions:
                await interaction.response.send_message("No extensions are currently loaded.", ephemeral=True)
                return

        # Sort extensions for better UX
        extensions.sort()

        # Discord select menu limit is 25 options
        view = HotswapView(extensions[:25], action)
        await view.reply(interaction, f"Select an extension to {action}:", ephemeral=True)

    # If debug_guild_id is set, restrict to that guild
    if settings.debug_guild_id:
        hotswap = app_commands.guilds(discord.Object(id=settings.debug_guild_id))(hotswap)


async def setup(bot: commands.Bot) -> None:
    """Load the HotswapCog."""
    await bot.add_cog(HotswapCog(bot))
