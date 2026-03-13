from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from capy_discord.services import dm


def make_member(member_id: int) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.mention = f"<@{member_id}>"
    member.send = AsyncMock()
    return member


@pytest.mark.asyncio
async def test_compose_rejects_everyone_role():
    guild = MagicMock(spec=discord.Guild)
    guild.default_role.id = 1

    with pytest.raises(dm.DmSafetyError, match="@everyone"):
        await dm.compose(
            guild,
            "Hello",
            audience=dm.Audience(role_ids=(1,)),
            policy=dm.Policy(allowed_role_ids=frozenset({1})),
            reason="test everyone rejection",
        )


@pytest.mark.asyncio
async def test_compose_rejects_audience_outside_policy():
    guild = MagicMock(spec=discord.Guild)
    guild.default_role.id = 999

    with pytest.raises(dm.DmSafetyError, match="outside the allowed policy"):
        await dm.compose(
            guild,
            "Hello",
            audience=dm.Audience(user_ids=(42,)),
            policy=dm.Policy(allowed_user_ids=frozenset({7})),
            reason="test policy mismatch",
        )


@pytest.mark.asyncio
async def test_compose_deduplicates_users_from_roles_and_explicit_ids():
    member = make_member(42)
    role = MagicMock(spec=discord.Role)
    role.members = [member]

    guild = MagicMock(spec=discord.Guild)
    guild.id = 123
    guild.default_role.id = 999
    guild.get_member.return_value = member
    guild.get_role.return_value = role

    draft = await dm.compose(
        guild,
        "Hello",
        audience=dm.Audience(user_ids=(42,), role_ids=(7,)),
        policy=dm.Policy(
            allowed_user_ids=frozenset({42}),
            allowed_role_ids=frozenset({7}),
            max_recipients=1,
        ),
        reason="test dedupe",
    )

    assert draft.preview.recipient_count == 1
    assert draft.preview.recipients == [member]
    assert draft.preview.skipped_ids == []


@pytest.mark.asyncio
async def test_compose_rejects_audience_above_cap():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123
    guild.default_role.id = 999
    guild.get_member.side_effect = [make_member(1), make_member(2)]

    with pytest.raises(dm.DmSafetyError, match="exceeds the cap"):
        await dm.compose(
            guild,
            "Hello",
            audience=dm.Audience(user_ids=(1, 2)),
            policy=dm.Policy(
                allowed_user_ids=frozenset({1, 2}),
                max_recipients=1,
            ),
            reason="test cap enforcement",
        )


@pytest.mark.asyncio
async def test_send_tracks_failures():
    ok_member = make_member(1)
    blocked_member = make_member(2)
    blocked_member.send.side_effect = discord.Forbidden(
        response=SimpleNamespace(status=403, reason="forbidden"),
        message="forbidden",
    )

    guild = MagicMock(spec=discord.Guild)
    guild.id = 123
    draft = dm.Draft(
        guild_id=123,
        preview=dm.AudiencePreview(recipients=[ok_member, blocked_member]),
        payload=dm.MessagePayload(content="Hello"),
        policy=dm.Policy(allowed_user_ids=frozenset({1, 2}), max_recipients=2),
        reason="test send failures",
    )

    result = await dm.send(guild, draft)

    assert result.sent_count == 1
    assert result.failed_ids == [2]
