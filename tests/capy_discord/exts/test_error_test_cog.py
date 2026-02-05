from unittest.mock import MagicMock

import discord
import pytest
from discord.ext import commands

from capy_discord.errors import UserFriendlyError
from capy_discord.exts.tools._error_test import ErrorTest


@pytest.fixture
def bot():
    return MagicMock(spec=commands.Bot)


@pytest.fixture
def cog(bot):
    return ErrorTest(bot)


@pytest.mark.asyncio
async def test_error_test_generic(cog):
    interaction = MagicMock(spec=discord.Interaction)
    with pytest.raises(ValueError, match="Generic error"):
        await cog.error_test.callback(cog, interaction, "generic")


@pytest.mark.asyncio
async def test_error_test_user_friendly(cog):
    interaction = MagicMock(spec=discord.Interaction)
    with pytest.raises(UserFriendlyError, match="Log"):
        await cog.error_test.callback(cog, interaction, "user-friendly")


@pytest.mark.asyncio
async def test_error_test_callback_generic(cog):
    interaction = MagicMock(spec=discord.Interaction)
    with pytest.raises(ValueError, match="Generic error"):
        await cog.error_test.callback(cog, interaction, "generic")


@pytest.mark.asyncio
async def test_error_test_callback_user_friendly(cog):
    interaction = MagicMock(spec=discord.Interaction)
    with pytest.raises(UserFriendlyError, match="Log"):
        await cog.error_test.callback(cog, interaction, "user-friendly")


@pytest.mark.asyncio
async def test_error_test_command_exception(cog):
    ctx = MagicMock(spec=commands.Context)
    with pytest.raises(Exception, match="Test Exception"):
        await cog.error_test_command.callback(cog, ctx)
