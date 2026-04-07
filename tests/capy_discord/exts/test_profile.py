from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from capy_discord.exts.profile._schemas import UserProfileDetailsSchema, UserProfileSchema
from capy_discord.exts.profile.profile import Profile


@pytest.fixture
def bot():
    mock_bot = MagicMock(spec=commands.Bot)
    mock_bot.profile_store = {}
    return mock_bot


@pytest.fixture
def cog(bot):
    return Profile(bot)


@pytest.fixture
def interaction():
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 123
    mock_interaction.user.display_name = "Capy"
    mock_interaction.user.display_avatar.url = "https://example.com/avatar.png"
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.response.send_modal = AsyncMock()
    mock_interaction.followup = MagicMock()
    mock_interaction.followup.send = AsyncMock()
    mock_interaction.original_response = AsyncMock(return_value=MagicMock())
    return mock_interaction


@pytest.mark.asyncio
async def test_profile_create_opens_modal_immediately(cog, interaction):
    await cog.profile.callback(cog, interaction, "create")

    interaction.response.send_message.assert_not_called()
    interaction.response.send_modal.assert_called_once()


@pytest.mark.asyncio
async def test_profile_create_with_existing_profile_shows_error(cog, interaction):
    cog.service._profiles[interaction.user.id] = UserProfileSchema(
        preferred_name="Existing User",
        student_id="123456789",
        school_email="existing@school.edu",
        graduation_year=2028,
        major="CS",
        minor="ITWS",
        description="Already here",
    )

    await cog.profile.callback(cog, interaction, "create")

    interaction.response.send_modal.assert_not_called()
    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "Profile Exists"


@pytest.mark.asyncio
async def test_profile_update_without_existing_profile_shows_error(cog, interaction):
    await cog.profile.callback(cog, interaction, "update")

    interaction.response.send_modal.assert_not_called()
    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "No Profile"


@pytest.mark.asyncio
async def test_profile_show_returns_embed_for_existing_profile(cog, interaction):
    cog.service._profiles[interaction.user.id] = UserProfileSchema(
        preferred_name="Capy Bara",
        student_id="123456789",
        school_email="capy@school.edu",
        graduation_year=2027,
        major="Computer Science",
        minor="ITWS",
        description="Likes clean code",
    )

    await cog.profile.callback(cog, interaction, "show")

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "Capy's Profile"


@pytest.mark.asyncio
async def test_profile_show_without_profile_shows_error(cog, interaction):
    await cog.profile.callback(cog, interaction, "show")

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "No Profile"


@pytest.mark.asyncio
async def test_handle_profile_details_submit_creates_profile(cog, interaction):
    details = UserProfileDetailsSchema(minor="ITWS", description="Builds bots")
    profile_data = {
        "preferred_name": "Capy Bara",
        "student_id": "123456789",
        "school_email": "capy@school.edu",
        "graduation_year": 2027,
        "major": "Computer Science",
    }

    await cog._handle_profile_details_submit(interaction, details, profile_data, "create")

    assert interaction.user.id in cog.service._profiles
    interaction.response.send_message.assert_called_once()
    embeds = interaction.response.send_message.await_args.kwargs["embeds"]
    assert embeds[0].title == "Profile Created"


@pytest.mark.asyncio
async def test_handle_profile_details_submit_with_invalid_data_shows_error(cog, interaction):
    details = UserProfileDetailsSchema(minor="ITWS", description="Builds bots")
    invalid_profile_data = {
        "preferred_name": "Capy Bara",
        "student_id": "invalid",
        "school_email": "capy@school.edu",
        "graduation_year": 2027,
        "major": "Computer Science",
    }

    await cog._handle_profile_details_submit(interaction, details, invalid_profile_data, "create")

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "Profile Validation Failed"
