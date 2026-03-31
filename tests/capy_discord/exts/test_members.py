from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from capy_discord.exts.members._profiles import create_profile_embed
from capy_discord.exts.members._schemas import UserProfileSchema
from capy_discord.exts.members.member import Member
from capy_discord.exts.members.profile import Profile


@pytest.fixture
def bot():
    mock_bot = MagicMock(spec=commands.Bot)
    mock_bot.profile_store = {}
    return mock_bot


@pytest.fixture
def profile_cog(bot):
    return Profile(bot)


@pytest.fixture
def member_cog(bot):
    return Member(bot)


@pytest.mark.asyncio
async def test_profile_create_opens_modal_immediately(profile_cog):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = 123
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.original_response = AsyncMock(return_value=MagicMock())

    await profile_cog.profile.callback(profile_cog, interaction, "create")

    interaction.response.send_message.assert_not_called()
    interaction.response.send_modal.assert_called_once()


@pytest.mark.asyncio
async def test_member_view_uses_same_embed_shape_as_profile_show(bot, member_cog):
    profile = UserProfileSchema(
        preferred_name="Test User",
        student_id="123456789",
        school_email="test@example.edu",
        graduation_year=2030,
        major="CS",
        minor="Math",
        description="Hello",
    )
    bot.profile_store[321] = profile

    member = MagicMock(spec=discord.Member)
    member.id = 321
    member.display_name = "Test User"
    member.display_avatar.url = "https://example.com/avatar.png"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await member_cog.view.callback(member_cog, interaction, member)

    embed = interaction.response.send_message.call_args.kwargs["embed"]
    expected = create_profile_embed(member, profile)

    assert embed.to_dict() == expected.to_dict()
    assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True
