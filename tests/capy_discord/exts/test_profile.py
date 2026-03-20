from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from capy_discord.exts.profile.profile import Profile


@pytest.fixture
def bot():
    mock_bot = MagicMock(spec=commands.Bot)
    mock_bot.profile_store = {}
    return mock_bot


@pytest.fixture
def cog(bot):
    return Profile(bot)


@pytest.mark.asyncio
async def test_profile_create_opens_modal_immediately(cog):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = 123
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.original_response = AsyncMock(return_value=MagicMock())

    await cog.profile.callback(cog, interaction, "create")

    interaction.response.send_message.assert_not_called()
    interaction.response.send_modal.assert_called_once()
