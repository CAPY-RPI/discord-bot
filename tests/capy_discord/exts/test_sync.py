from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from capy_discord.exts.tools.sync import Sync


@pytest.fixture
def bot():
    mock_bot = MagicMock(spec=commands.Bot)
    mock_bot.tree = MagicMock()
    mock_bot.tree.sync = AsyncMock(return_value=[])
    return mock_bot


@pytest.fixture
def cog(bot):
    return Sync(bot)


@pytest.mark.asyncio
async def test_sync_command_error_bubbles(cog, bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.bot = bot
    ctx.author.id = 123
    ctx.send = AsyncMock()
    bot.tree.sync.side_effect = Exception("Sync failed")

    with pytest.raises(Exception, match="Sync failed"):
        await cog.sync.callback(cog, ctx)


@pytest.mark.asyncio
async def test_sync_slash_error_bubbles(cog, bot):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.user.id = 123
    interaction.guild_id = 456

    bot.tree.sync.side_effect = Exception("Slash sync failed")

    with pytest.raises(Exception, match="Slash sync failed"):
        await cog.sync_slash.callback(cog, interaction)
