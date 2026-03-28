from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from capy_discord.exts.tools.ping import Ping


@pytest.fixture
def bot():
    mock_bot = MagicMock(spec=commands.Bot)
    mock_bot.latency = 0.1
    return mock_bot


@pytest.fixture
def cog(bot):
    return Ping(bot)


@pytest.mark.asyncio
async def test_ping_success(cog):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.ping.callback(cog, interaction)

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    embed = kwargs.get("embed") or args[0]
    assert isinstance(embed, discord.Embed)
    assert embed.description == "Pong! 100 ms Latency!"


@pytest.mark.asyncio
async def test_ping_error_bubbles(cog, bot):
    type(bot).latency = property(lambda _: 1 / 0)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with pytest.raises(ZeroDivisionError):
        await cog.ping.callback(cog, interaction)
