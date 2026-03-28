from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from capy_discord.exts.setup.setup import Onboarding, utc_now


@pytest.fixture
def bot():
    mock_bot = MagicMock(spec=commands.Bot)
    mock_bot.user = SimpleNamespace(id=999)
    return mock_bot


@pytest.fixture
def cog(bot):
    return Onboarding(bot)


def _perm(view: bool, send: bool = False):
    return SimpleNamespace(view_channel=view, send_messages=send)


def _interaction_with_permissions(*, manage_guild: bool) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.permissions = discord.Permissions(manage_guild=manage_guild)
    return interaction


@pytest.mark.asyncio
async def test_on_guild_join_posts_setup_message_to_first_public_channel(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123
    guild.default_role = MagicMock()

    bot_member = MagicMock()
    guild.me = bot_member

    private_channel = MagicMock(spec=discord.TextChannel)
    public_channel = MagicMock(spec=discord.TextChannel)
    private_channel.id = 1
    public_channel.id = 2
    private_channel.send = AsyncMock()
    public_channel.send = AsyncMock()

    def private_permissions_for(target):
        if target is guild.default_role:
            return _perm(view=False)
        return _perm(view=True, send=True)

    def public_permissions_for(target):
        if target is guild.default_role:
            return _perm(view=True)
        return _perm(view=True, send=True)

    private_channel.permissions_for.side_effect = private_permissions_for
    public_channel.permissions_for.side_effect = public_permissions_for
    guild.text_channels = [private_channel, public_channel]

    await cog.on_guild_join(guild)

    private_channel.send.assert_not_called()
    public_channel.send.assert_called_once()
    sent_text = public_channel.send.call_args.args[0]
    assert "Run these commands to configure setup" in sent_text
    assert "/setup roles" in sent_text


@pytest.mark.asyncio
async def test_on_member_join_skips_with_incomplete_setup(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 100

    member = MagicMock(spec=discord.Member)
    member.id = 200
    member.guild = guild

    await cog.on_member_join(member)

    assert cog._user_state_store == {}


@pytest.mark.asyncio
async def test_on_member_join_sets_pending_and_sends_welcome(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 200

    welcome_channel = MagicMock(spec=discord.TextChannel)
    welcome_channel.id = 333
    welcome_channel.send = AsyncMock(return_value=MagicMock(spec=discord.Message))
    guild.get_channel.return_value = welcome_channel

    config = cog._ensure_setup(guild.id)
    config.welcome_channel_id = welcome_channel.id
    config.member_role_id = 777
    config.rules_location = "#rules"

    member = MagicMock(spec=discord.Member)
    member.id = 300
    member.mention = "<@300>"
    member.guild = guild
    member.send = AsyncMock()
    cog._schedule_grace_period_check = MagicMock()

    await cog.on_member_join(member)

    state = cog._get_user_state(guild.id, member.id)
    assert state.status == "pending"
    assert state.attempts == 1
    welcome_channel.send.assert_called_once()
    assert "Accept Rules" in welcome_channel.send.call_args.args[0]
    assert "view" in welcome_channel.send.call_args.kwargs
    cog._schedule_grace_period_check.assert_called_once_with(guild.id, member.id, 1)


@pytest.mark.parametrize(
    "command_name",
    ["setup_summary", "setup_roles", "setup_channels", "setup_onboarding", "setup_reset"],
)
@pytest.mark.asyncio
async def test_setup_commands_require_manage_guild_for_non_managers(cog, command_name):
    interaction = _interaction_with_permissions(manage_guild=False)

    with pytest.raises(app_commands.MissingPermissions) as exc_info:
        await getattr(cog, command_name)._check_can_run(interaction)

    assert exc_info.value.missing_permissions == ["manage_guild"]


@pytest.mark.asyncio
async def test_setup_roles_updates_config(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 99

    role_1 = MagicMock(spec=discord.Role)
    role_1.id = 1
    role_2 = MagicMock(spec=discord.Role)
    role_2.id = 2
    role_3 = MagicMock(spec=discord.Role)
    role_3.id = 3
    member_role = MagicMock(spec=discord.Role)
    member_role.id = 50

    roles = {1: role_1, 2: role_2, 3: role_3, 50: member_role}
    guild.get_role.side_effect = roles.get

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.setup_roles.callback(
        cog,
        interaction,
        admin_roles="<@&2>, <@&1>",
        moderator_roles="3 3",
        member_role=member_role,
    )

    config = cog._ensure_setup(guild.id)
    assert config.admin_role_ids == [1, 2]
    assert config.moderator_role_ids == [3]
    assert config.member_role_id == 50


@pytest.mark.asyncio
async def test_setup_onboarding_updates_config(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 101

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.setup_onboarding.callback(
        cog,
        interaction,
        enabled=False,
        welcome_dm_enabled=True,
        auto_kick_unverified=True,
        grace_period_hours=48,
        log_events=False,
        rules_location="clear",
        message="Hello {user}",
    )

    config = cog._ensure_setup(guild.id)
    assert config.enabled is False
    assert config.welcome_dm_enabled is True
    assert config.auto_kick_unverified is True
    assert config.grace_period_hours == 48
    assert config.log_events is False
    assert config.rules_location is None
    assert config.onboarding_message_template == "Hello {user}"


@pytest.mark.asyncio
async def test_handle_accept_assigns_role_and_marks_verified(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 555

    role = 20
    member = MagicMock(spec=discord.Member)
    member.id = 777
    member.mention = "<@777>"
    member.roles = []
    member.add_roles = AsyncMock()

    bot_member = MagicMock()
    bot_member.guild_permissions = SimpleNamespace(manage_roles=True)
    bot_member.top_role = 500
    guild.me = bot_member
    guild.get_role.return_value = role
    guild.get_member.return_value = member

    config = cog._ensure_setup(guild.id)
    config.member_role_id = role
    state = cog._get_user_state(guild.id, member.id)
    state.status = "pending"
    state.started_at_utc = utc_now()
    state.attempts = 1

    grace_task = MagicMock()
    grace_task.done.return_value = False
    cog._grace_tasks[cog._state_key(guild.id, member.id)] = grace_task

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    completed = await cog._handle_accept(interaction, member.id, 1)

    assert completed is True
    member.add_roles.assert_called_once_with(role, reason="Completed onboarding rule acceptance")
    assert state.status == "verified"
    grace_task.cancel.assert_called_once()
    assert cog._state_key(guild.id, member.id) not in cog._grace_tasks
    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_log_message_skips_when_log_events_disabled(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 202

    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    guild.get_channel.return_value = channel

    config = cog._ensure_setup(guild.id)
    config.log_channel_id = 999
    config.log_events = False

    await cog._send_log_message(guild, config, "ignored")

    channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_enforce_grace_period_kicks_unverified_member(cog, monkeypatch):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 303

    member = MagicMock(spec=discord.Member)
    member.id = 404
    member.mention = "<@404>"
    member.top_role = 1
    member.kick = AsyncMock()

    bot_member = MagicMock()
    bot_member.guild_permissions = SimpleNamespace(kick_members=True)
    bot_member.top_role = 500
    guild.me = bot_member
    guild.get_member.side_effect = lambda user_id: member if user_id == member.id else None
    cog.bot.get_guild.return_value = guild

    config = cog._ensure_setup(guild.id)
    config.auto_kick_unverified = True
    config.grace_period_hours = 1
    config.log_events = False

    state = cog._get_user_state(guild.id, member.id)
    state.status = "pending"
    state.started_at_utc = utc_now()
    state.attempts = 1

    async def fake_sleep(_seconds: float) -> None:
        state.started_at_utc = utc_now() - timedelta(hours=2)

    monkeypatch.setattr("capy_discord.exts.setup.setup.asyncio.sleep", fake_sleep)

    await cog._enforce_grace_period(guild.id, member.id, 1)

    member.kick.assert_called_once_with(reason="Did not complete onboarding within the configured grace period")


@pytest.mark.asyncio
async def test_timeout_resets_state_before_retry_and_cancels_previous_grace_task(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 808

    member = MagicMock(spec=discord.Member)
    member.id = 909
    member.mention = "<@909>"
    member.guild = guild

    cog.bot.get_guild.return_value = guild
    guild.get_member.return_value = member

    state = cog._get_user_state(guild.id, member.id)
    state.status = "pending"
    state.started_at_utc = utc_now()
    state.completed_at_utc = utc_now()
    state.attempts = 1

    config = cog._ensure_setup(guild.id)
    config.log_events = False

    grace_task = MagicMock()
    grace_task.done.return_value = False
    cog._grace_tasks[cog._state_key(guild.id, member.id)] = grace_task

    captured_state = {}

    async def fake_send_verification_prompt(target_member, *, is_retry: bool = False) -> bool:
        current = cog._get_user_state(target_member.guild.id, target_member.id)
        captured_state["status"] = current.status
        captured_state["started_at_utc"] = current.started_at_utc
        captured_state["completed_at_utc"] = current.completed_at_utc
        captured_state["attempts"] = current.attempts
        captured_state["is_retry"] = is_retry
        return True

    cog._send_verification_prompt = fake_send_verification_prompt

    await cog._handle_verification_timeout(guild.id, 1, member.id)

    grace_task.cancel.assert_called_once()
    assert captured_state == {
        "status": "new",
        "started_at_utc": None,
        "completed_at_utc": None,
        "attempts": 1,
        "is_retry": True,
    }


@pytest.mark.asyncio
async def test_stale_grace_period_task_does_not_kick_after_timeout_retry(cog, monkeypatch):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 818

    member = MagicMock(spec=discord.Member)
    member.id = 919
    member.mention = "<@919>"
    member.top_role = 1
    member.guild = guild
    member.kick = AsyncMock()

    bot_member = MagicMock()
    bot_member.guild_permissions = SimpleNamespace(kick_members=True)
    bot_member.top_role = 50
    guild.me = bot_member
    guild.get_member.side_effect = lambda user_id: member if user_id == member.id else None
    cog.bot.get_guild.return_value = guild

    config = cog._ensure_setup(guild.id)
    config.auto_kick_unverified = True
    config.grace_period_hours = 1
    config.log_events = False

    state = cog._get_user_state(guild.id, member.id)
    state.status = "pending"
    state.started_at_utc = utc_now()
    state.attempts = 2

    async def fake_sleep(_seconds: float) -> None:
        state.started_at_utc = utc_now() - timedelta(hours=2)

    monkeypatch.setattr("capy_discord.exts.setup.setup.asyncio.sleep", fake_sleep)

    await cog._enforce_grace_period(guild.id, member.id, 1)

    member.kick.assert_not_called()


@pytest.mark.asyncio
async def test_retry_view_allows_same_user_to_complete_onboarding(cog):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 828

    role = 222

    welcome_messages = []

    def make_message(*_args, **_kwargs) -> MagicMock:
        message = MagicMock(spec=discord.Message)
        message.edit = AsyncMock()
        welcome_messages.append(message)
        return message

    welcome_channel = MagicMock(spec=discord.TextChannel)
    welcome_channel.id = 444
    welcome_channel.send = AsyncMock(side_effect=make_message)

    member = MagicMock(spec=discord.Member)
    member.id = 929
    member.mention = "<@929>"
    member.guild = guild
    member.roles = []
    member.add_roles = AsyncMock()
    member.send = AsyncMock()
    member.top_role = 1

    bot_member = MagicMock()
    bot_member.guild_permissions = SimpleNamespace(manage_roles=True)
    bot_member.top_role = 500
    guild.me = bot_member
    guild.get_channel.return_value = welcome_channel
    guild.get_role.return_value = role
    guild.get_member.return_value = member
    cog.bot.get_guild.return_value = guild
    cog._schedule_grace_period_check = MagicMock()

    config = cog._ensure_setup(guild.id)
    config.welcome_channel_id = welcome_channel.id
    config.member_role_id = role
    config.rules_location = "#rules"
    config.log_events = False

    await cog.on_member_join(member)

    first_view = welcome_channel.send.call_args_list[0].kwargs["view"]
    await first_view.on_timeout()

    assert welcome_channel.send.call_count == 2
    second_view = welcome_channel.send.call_args_list[1].kwargs["view"]

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = SimpleNamespace(id=member.id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await second_view.children[0].callback(interaction)

    member.add_roles.assert_called_once_with(role, reason="Completed onboarding rule acceptance")
    state = cog._get_user_state(guild.id, member.id)
    assert state.status == "verified"


@pytest.mark.asyncio
async def test_verified_user_is_not_removed_by_old_grace_task(cog, monkeypatch):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 838

    member = MagicMock(spec=discord.Member)
    member.id = 939
    member.mention = "<@939>"
    member.top_role = 1
    member.guild = guild
    member.kick = AsyncMock()

    bot_member = MagicMock()
    bot_member.guild_permissions = SimpleNamespace(kick_members=True, manage_roles=True)
    bot_member.top_role = 500
    guild.me = bot_member
    guild.get_member.return_value = member
    guild.get_role.return_value = 123
    cog.bot.get_guild.return_value = guild

    config = cog._ensure_setup(guild.id)
    config.member_role_id = 123
    config.auto_kick_unverified = True
    config.grace_period_hours = 1
    config.log_events = False

    state = cog._get_user_state(guild.id, member.id)
    state.status = "pending"
    state.started_at_utc = utc_now()
    state.attempts = 1

    async def fake_sleep(_seconds: float) -> None:
        state.started_at_utc = utc_now() - timedelta(hours=2)

    monkeypatch.setattr("capy_discord.exts.setup.setup.asyncio.sleep", fake_sleep)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    completed = await cog._handle_accept(interaction, member.id, 1)

    assert completed is True
    await cog._enforce_grace_period(guild.id, member.id, 1)
    member.kick.assert_not_called()
