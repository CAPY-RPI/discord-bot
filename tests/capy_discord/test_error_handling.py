from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from capy_discord.bot import Bot
from capy_discord.errors import UserFriendlyError


@pytest.fixture
def bot():
    intents = discord.Intents.default()
    b = Bot(command_prefix="!", intents=intents)
    b.log = MagicMock()
    return b


@pytest.mark.asyncio
async def test_on_tree_error_user_friendly(bot):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    error = UserFriendlyError("Internal", "User Message")
    # app_commands.CommandInvokeError wraps the actual error
    invoke_error = app_commands.CommandInvokeError(MagicMock(), error)

    await bot.on_tree_error(interaction, invoke_error)

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    embed = kwargs.get("embed") or args[0]
    assert embed.description == "User Message"
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_on_tree_error_generic(bot):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.command = MagicMock()
    interaction.command.module = "exts.test_cog"
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    error = Exception("Unexpected")
    invoke_error = app_commands.CommandInvokeError(MagicMock(), error)

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        await bot.on_tree_error(interaction, invoke_error)
        mock_get_logger.assert_called_with("exts.test_cog")
        mock_logger.exception.assert_called_once()

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    embed = kwargs.get("embed") or args[0]
    assert "An unexpected error occurred" in embed.description


@pytest.mark.asyncio
async def test_on_tree_error_is_done(bot):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = True
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    error = UserFriendlyError("Internal", "User Message")
    invoke_error = app_commands.CommandInvokeError(MagicMock(), error)

    await bot.on_tree_error(interaction, invoke_error)

    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    embed = kwargs.get("embed") or args[0]
    assert embed.description == "User Message"
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_on_command_error_user_friendly(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.send = AsyncMock()

    error = UserFriendlyError("Internal", "User Message")
    command_error = commands.CommandInvokeError(error)

    await bot.on_command_error(ctx, command_error)

    ctx.send.assert_called_once()
    args, kwargs = ctx.send.call_args
    embed = kwargs.get("embed") or args[0]
    assert embed.description == "User Message"


@pytest.mark.asyncio
async def test_on_command_error_generic(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.command = MagicMock()
    ctx.command.module = "exts.prefix_cog"
    ctx.send = AsyncMock()

    error = Exception("Unexpected")
    command_error = commands.CommandInvokeError(error)

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        await bot.on_command_error(ctx, command_error)
        mock_get_logger.assert_called_with("exts.prefix_cog")
        mock_logger.exception.assert_called_once()

    ctx.send.assert_called_once()
    args, kwargs = ctx.send.call_args
    embed = kwargs.get("embed") or args[0]
    assert "An unexpected error occurred" in embed.description


@pytest.mark.asyncio
async def test_on_tree_error_fallback_logger(bot):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.command = None
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False

    error = Exception("Unexpected")
    invoke_error = app_commands.CommandInvokeError(MagicMock(), error)

    await bot.on_tree_error(interaction, invoke_error)

    bot.log.exception.assert_called_once()


@pytest.mark.asyncio
async def test_on_command_error_fallback_logger(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.command = None
    ctx.send = AsyncMock()

    error = Exception("Unexpected")
    command_error = commands.CommandInvokeError(error)

    await bot.on_command_error(ctx, command_error)

    bot.log.exception.assert_called_once()
