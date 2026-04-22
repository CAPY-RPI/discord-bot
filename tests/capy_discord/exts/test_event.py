import secrets
from datetime import date, datetime, time, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from capy_discord.config import settings
from capy_discord.database import BackendAPIError, HTTP_STATUS_NOT_FOUND
from capy_discord.exts.event._schemas import EventSchema
from capy_discord.exts.event.event import ConfirmDeleteView, Event, EventDropdownSelect, EventDropdownView, setup

TEST_GUILD_ID = 1_000_000_000_000_000_000 + secrets.randbelow(8_000_000_000_000_000_000)


@pytest.fixture
def bot() -> MagicMock:
    return MagicMock(spec=commands.Bot)


@pytest.fixture
def cog(bot: MagicMock) -> Event:
    return Event(bot)


@pytest.fixture
def interaction() -> MagicMock:
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild_id = TEST_GUILD_ID
    mock_interaction.response = MagicMock()
    mock_interaction.response.defer = AsyncMock()
    mock_interaction.response.edit_message = AsyncMock()
    mock_interaction.response.send_modal = AsyncMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.followup = MagicMock()
    mock_interaction.followup.send = AsyncMock()
    return mock_interaction


def _backend_event(
    *,
    eid: str,
    title: str,
    event_time: str,
    org_id: str | None = None,
) -> dict[str, str]:
    event: dict[str, str] = {
        "eid": eid,
        "title": title,
        "event_time": event_time,
        "description": "",
        "location": "DCC",
    }
    if org_id is not None:
        event["org_id"] = org_id
    return event


def _event_schema(*, name: str, event_id: str | None = None) -> EventSchema:
    return EventSchema(
        event_id=event_id,
        event_name=name,
        event_date=date(2026, 4, 14),
        event_time=time(10, 0),
        location="DCC",
        description="",
    )


def _guild(*, guild_id: int = TEST_GUILD_ID, name: str = "Capy Guild") -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = name
    return guild


@pytest.mark.asyncio
async def test_resolve_org_id_uses_existing_backend_org(cog: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_bot_organization_by_guild_id = AsyncMock(return_value={"oid": "org-test-123", "guild_id": TEST_GUILD_ID})
    client.create_bot_organization = AsyncMock()
    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    org_id = await cog._resolve_org_id(_guild())

    assert org_id == "org-test-123"
    client.create_bot_organization.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_org_id_creates_backend_org_when_missing(cog: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_bot_organization_by_guild_id = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.create_bot_organization = AsyncMock(return_value={"oid": "org-created", "guild_id": TEST_GUILD_ID})
    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    guild = _guild(name="Capy Test Server")
    org_id = await cog._resolve_org_id(guild)

    assert org_id == "org-created"
    client.create_bot_organization.assert_awaited_once_with({"guild_id": guild.id, "name": guild.name})


@pytest.mark.asyncio
async def test_fetch_backend_events_uses_primary_org_route(cog: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.list_events_by_organization = AsyncMock(
        return_value=[
            _backend_event(eid="evt-2", title="Later", event_time="2026-04-14T15:00:00Z", org_id="org-1"),
            _backend_event(eid="evt-1", title="Sooner", event_time="2026-04-14T14:00:00Z", org_id="org-1"),
        ]
    )
    client.list_organization_events = AsyncMock()
    client.list_events = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    events = await cog._fetch_backend_events("org-1")

    assert [event.event_id for event in events] == ["evt-1", "evt-2"]
    client.list_organization_events.assert_not_awaited()
    client.list_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_backend_events_falls_back_to_organization_route(
    cog: Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MagicMock()
    client.list_events_by_organization = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.list_organization_events = AsyncMock(
        return_value=[
            _backend_event(eid="evt-1", title="From Org Route", event_time="2026-04-14T14:00:00Z", org_id="org-1")
        ]
    )
    client.list_events = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    events = await cog._fetch_backend_events("org-1")

    assert [event.event_id for event in events] == ["evt-1"]
    client.list_organization_events.assert_awaited_once_with("org-1")
    client.list_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_backend_events_falls_back_to_global_list_and_filters(
    cog: Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MagicMock()
    client.list_events_by_organization = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.list_organization_events = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.list_events = AsyncMock(
        return_value=[
            _backend_event(eid="evt-keep-1", title="Target Org", event_time="2026-04-14T14:00:00Z", org_id="org-1"),
            _backend_event(eid="evt-drop", title="Other Org", event_time="2026-04-14T13:00:00Z", org_id="org-2"),
            _backend_event(eid="evt-keep-2", title="No Org Field", event_time="2026-04-14T12:00:00Z"),
        ]
    )

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    events = await cog._fetch_backend_events("org-1")

    assert [event.event_id for event in events] == ["evt-keep-2", "evt-keep-1"]
    client.list_events.assert_awaited_once_with(limit=100, offset=0)


@pytest.mark.asyncio
async def test_fetch_backend_events_returns_empty_on_non_not_found(cog: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.list_events_by_organization = AsyncMock(side_effect=BackendAPIError("boom", status_code=500))
    client.list_organization_events = AsyncMock()
    client.list_events = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    events = await cog._fetch_backend_events("org-1")

    assert events == []
    client.list_organization_events.assert_not_awaited()
    client.list_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_show_action_uses_fallback_and_sends_dropdown(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _instant_wait(view: Any) -> None:
        view.selected = True

    client = MagicMock()
    client.list_events_by_organization = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.list_organization_events = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.list_events = AsyncMock(
        return_value=[
            _backend_event(eid="evt-1", title="Show Event", event_time="2026-04-14T14:00:00Z", org_id="org-1")
        ]
    )

    interaction.guild = _guild()
    monkeypatch.setattr(cog, "_resolve_org_id", AsyncMock(return_value="org-1"))
    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)
    monkeypatch.setattr("capy_discord.exts.event.event.EventDropdownView.wait", _instant_wait)

    await cog.handle_show_action(interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()
    kwargs = interaction.followup.send.await_args.kwargs
    assert kwargs["content"] == "Select an event to view:"
    assert kwargs["ephemeral"] is True
    assert kwargs.get("view") is not None
    client.list_events.assert_awaited_once_with(limit=100, offset=0)


@pytest.mark.asyncio
async def test_handle_edit_action_uses_fallback_and_sends_dropdown(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _instant_wait(view: Any) -> None:
        view.selected = True

    client = MagicMock()
    client.list_events_by_organization = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.list_organization_events = AsyncMock(
        side_effect=BackendAPIError("missing", status_code=HTTP_STATUS_NOT_FOUND)
    )
    client.list_events = AsyncMock(
        return_value=[
            _backend_event(eid="evt-2", title="Edit Event", event_time="2026-04-14T14:00:00Z", org_id="org-1")
        ]
    )

    interaction.guild = _guild()
    monkeypatch.setattr(cog, "_resolve_org_id", AsyncMock(return_value="org-1"))
    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)
    monkeypatch.setattr("capy_discord.exts.event.event.EventDropdownView.wait", _instant_wait)

    await cog.handle_edit_action(interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()
    kwargs = interaction.followup.send.await_args.kwargs
    assert kwargs["content"] == "Select an event to edit:"
    assert kwargs["ephemeral"] is True
    assert kwargs.get("view") is not None
    client.list_events.assert_awaited_once_with(limit=100, offset=0)


@pytest.mark.asyncio
async def test_handle_list_action_no_server_returns_error(cog: Event, interaction: MagicMock) -> None:
    interaction.guild_id = None

    await cog.handle_list_action(interaction)

    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "No Server"


@pytest.mark.asyncio
async def test_handle_list_action_sorts_upcoming_and_past(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interaction.guild = _guild()
    monkeypatch.setattr(cog, "_resolve_org_id", AsyncMock(return_value="org-1"))
    now = datetime.now(ZoneInfo("UTC"))
    events = [
        _event_schema(name="Past 2"),
        _event_schema(name="Future 1"),
        _event_schema(name="Past 1"),
        _event_schema(name="Future 2"),
    ]

    timeline = {
        "Future 1": now + timedelta(hours=2),
        "Future 2": now + timedelta(hours=1),
        "Past 1": now - timedelta(hours=1),
        "Past 2": now - timedelta(hours=2),
    }

    monkeypatch.setattr(cog, "_fetch_backend_events", AsyncMock(return_value=events))
    monkeypatch.setattr(cog, "_event_datetime", MagicMock(side_effect=lambda event: timeline[event.event_name]))

    await cog.handle_list_action(interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert [field.name for field in embed.fields] == ["Future 2", "Future 1", "[OLD] Past 1", "[OLD] Past 2"]


@pytest.mark.asyncio
async def test_handle_event_submit_success_calls_backend(
    cog: Event, interaction: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MagicMock()
    client.create_event = AsyncMock()
    interaction.guild = _guild()
    interaction.message = None
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.edit_message = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)
    monkeypatch.setattr(cog, "_resolve_org_id", AsyncMock(return_value="org-1"))
    event = _event_schema(name="Create Event")

    await cog._handle_event_submit(interaction, event)

    client.create_event.assert_awaited_once()
    kwargs = client.create_event.await_args_list[0].args[0]
    assert kwargs["title"] == "Create Event"
    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "Event Created"


@pytest.mark.asyncio
async def test_handle_event_submit_backend_error_returns_error_embed(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.create_event = AsyncMock(side_effect=BackendAPIError("bad", status_code=400))
    interaction.guild = _guild()
    interaction.message = None
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.edit_message = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)
    monkeypatch.setattr(cog, "_resolve_org_id", AsyncMock(return_value="org-1"))

    await cog._handle_event_submit(interaction, _event_schema(name="Create Event"))

    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "Failed to Create Event"


@pytest.mark.asyncio
async def test_handle_event_update_success(cog: Event, interaction: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.update_event = AsyncMock()
    interaction.guild = _guild()
    interaction.message = None
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.edit_message = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)
    monkeypatch.setattr(cog, "_resolve_org_id", AsyncMock(return_value="org-1"))
    original_event = _event_schema(name="Original", event_id="evt-123")
    updated_event = _event_schema(name="Updated Name")

    await cog._handle_event_update(interaction, updated_event, original_event)

    client.update_event.assert_awaited_once()
    assert client.update_event.await_args_list[0].args[0] == "evt-123"
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "Event Updated"


@pytest.mark.asyncio
async def test_handle_event_update_missing_event_id(cog: Event, interaction: MagicMock) -> None:
    interaction.guild = _guild()
    interaction.message = None
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.edit_message = AsyncMock()

    original_event = _event_schema(name="Original", event_id=None)
    updated_event = _event_schema(name="Updated Name")

    await cog._handle_event_update(interaction, updated_event, original_event)

    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "Event Not Found"


@pytest.mark.asyncio
async def test_on_delete_select_success(cog: Event, interaction: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    class _ConfirmDeleteViewStub:
        def __init__(self) -> None:
            self.value = True

        async def wait(self) -> None:
            return None

    client = MagicMock()
    client.delete_event = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.ConfirmDeleteView", _ConfirmDeleteViewStub)
    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    await cog._on_delete_select(interaction, _event_schema(name="Delete Me", event_id="evt-42"))

    client.delete_event.assert_awaited_once_with("evt-42")
    assert interaction.followup.send.await_count == 1
    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Event Deleted"


@pytest.mark.asyncio
async def test_on_delete_select_timeout(cog: Event, interaction: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    class _ConfirmDeleteViewStub:
        def __init__(self) -> None:
            self.value = None

        async def wait(self) -> None:
            return None

    monkeypatch.setattr("capy_discord.exts.event.event.ConfirmDeleteView", _ConfirmDeleteViewStub)

    await cog._on_delete_select(interaction, _event_schema(name="Delete Me", event_id="evt-42"))

    assert interaction.followup.send.await_count == 1
    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Deletion Timed Out"


@pytest.mark.asyncio
async def test_get_events_for_dropdown_timeout_sends_timeout_embed(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DropdownViewStub:
        def __init__(self, *_args, **_kwargs) -> None:
            self.cancelled = False
            self.selected = False

        async def wait(self) -> None:
            return None

    monkeypatch.setattr(
        cog, "_fetch_backend_events", AsyncMock(return_value=[_event_schema(name="Event 1", event_id="evt-1")])
    )
    interaction.guild = _guild()
    monkeypatch.setattr(cog, "_resolve_org_id", AsyncMock(return_value="org-1"))
    monkeypatch.setattr("capy_discord.exts.event.event.EventDropdownView", _DropdownViewStub)

    await cog._get_events_for_dropdown(interaction, "show", AsyncMock())

    assert interaction.followup.send.await_count == 2
    timeout_embed = interaction.followup.send.await_args_list[1].kwargs["embed"]
    assert timeout_embed.title == "Selection Timed Out"


@pytest.mark.asyncio
async def test_is_user_registered_returns_true_when_checkmark_reaction_contains_user(
    cog: Event,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guild = _guild()
    user = MagicMock(spec=discord.User)
    event = _event_schema(name="RSVP Event")
    cog.event_announcements[guild.id] = {event.event_name: 55}

    async def _users_iter():
        yield user

    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.users = MagicMock(return_value=_users_iter())
    message = MagicMock()
    message.reactions = [reaction]

    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    monkeypatch.setattr(cog, "_get_announcement_channel", lambda _guild: channel)

    assert await cog._is_user_registered(event, guild, user) is True


@pytest.mark.asyncio
async def test_on_announce_select_no_channel_returns_error(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interaction.guild = _guild(guild_id=interaction.guild_id)
    interaction.response.is_done = MagicMock(return_value=False)
    monkeypatch.setattr(cog, "_get_announcement_channel", lambda _guild: None)

    await cog._on_announce_select(interaction, _event_schema(name="Announce Event", event_id="evt-1"))

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "No Announcement Channel"


@pytest.mark.asyncio
async def test_on_announce_select_success_tracks_message_id(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guild = _guild(guild_id=interaction.guild_id)
    interaction.guild = guild
    interaction.response.is_done = MagicMock(return_value=False)

    bot_member = MagicMock()
    guild.me = bot_member

    permissions = MagicMock()
    permissions.send_messages = True

    message = MagicMock()
    message.id = 444
    message.add_reaction = AsyncMock()

    channel = MagicMock(spec=discord.TextChannel)
    channel.name = settings.announcement_channel_name
    channel.mention = "#announcements"
    channel.permissions_for = MagicMock(return_value=permissions)
    channel.send = AsyncMock(return_value=message)

    monkeypatch.setattr(cog, "_get_announcement_channel", MagicMock(return_value=channel))

    event = _event_schema(name="Announce Event", event_id="evt-1")

    await cog._on_announce_select(interaction, event)

    channel.send.assert_awaited_once()
    assert message.add_reaction.await_count == 2
    assert cog.event_announcements[guild.id][event.event_name] == 444
    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Event Announced"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "method_name"),
    [
        ("create", "handle_create_action"),
        ("list", "handle_list_action"),
        ("announce", "handle_announce_action"),
    ],
)
async def test_event_command_routes_to_expected_handler(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    method_name: str,
) -> None:
    handler = AsyncMock()
    monkeypatch.setattr(cog, method_name, handler)

    choice = app_commands.Choice(name=action, value=action)
    callback: Any = cog.event.callback
    await callback(cog, interaction, choice)

    handler.assert_awaited_once_with(interaction)


@pytest.mark.asyncio
async def test_handle_create_action_sends_modal(cog: Event, interaction: MagicMock) -> None:
    interaction.user = MagicMock()

    await cog.handle_create_action(interaction)

    interaction.response.send_modal.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_edit_select_sends_prefilled_modal(cog: Event, interaction: MagicMock) -> None:
    event = _event_schema(name="Editable", event_id="evt-9")

    await cog._on_edit_select(interaction, event)

    interaction.response.send_modal.assert_awaited_once()
    modal = interaction.response.send_modal.await_args.args[0]
    assert modal._inputs["event_name"].default == "Editable"
    assert modal._inputs["event_date"].default == "04-14-2026"
    assert modal._inputs["event_time"].default == "10:00"


@pytest.mark.asyncio
async def test_respond_from_modal_prefers_edit_when_message_present(cog: Event, interaction: MagicMock) -> None:
    interaction.message = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.edit_message = AsyncMock()

    embed = discord.Embed(title="Test")
    await cog._respond_from_modal(interaction, embed)

    interaction.response.edit_message.assert_awaited_once()
    interaction.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_from_modal_uses_followup_when_response_done(cog: Event, interaction: MagicMock) -> None:
    interaction.message = None
    interaction.response.is_done = MagicMock(return_value=True)

    embed = discord.Embed(title="Test")
    await cog._respond_from_modal(interaction, embed)

    interaction.followup.send.assert_awaited_once()


def test_decode_event_description_prefixed_value(cog: Event) -> None:
    name, description = cog._decode_event_description("[capy_event_name]My Event\nDetails here")

    assert name == "My Event"
    assert description == "Details here"


def test_from_backend_event_uses_fallback_decoder(cog: Event) -> None:
    event = cog._from_backend_event(
        {
            "eid": "evt-legacy",
            "description": "[capy_event_name]Legacy Event\nLegacy details",
            "event_time": "2026-04-14T14:00:00Z",
            "location": "DCC",
        }
    )

    assert event.event_name == "Legacy Event"
    assert event.description == "Legacy details"


def test_from_backend_event_raises_for_invalid_time(cog: Event) -> None:
    with pytest.raises(ValueError, match="Invalid event_time format"):
        cog._from_backend_event(
            {
                "eid": "evt-bad",
                "title": "Bad Time",
                "event_time": "not-a-time",
                "description": "",
                "location": "",
            }
        )


@pytest.mark.asyncio
async def test_handle_myevents_action_no_server_returns_error(cog: Event, interaction: MagicMock) -> None:
    interaction.guild = None

    await cog.handle_myevents_action(interaction)

    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "No Server"


@pytest.mark.asyncio
async def test_handle_myevents_action_no_events_returns_error(cog: Event, interaction: MagicMock) -> None:
    interaction.guild = MagicMock(spec=discord.Guild)
    cog._resolve_org_id = AsyncMock(return_value="org-1")  # type: ignore[method-assign]
    monkey_fetch = AsyncMock(return_value=[])
    cog._fetch_backend_events = monkey_fetch  # type: ignore[method-assign]

    await cog.handle_myevents_action(interaction)

    interaction.response.send_message.assert_awaited_once()
    interaction.response.defer.assert_not_awaited()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "No Events"


@pytest.mark.asyncio
async def test_handle_myevents_action_no_registered_events(cog: Event, interaction: MagicMock) -> None:
    interaction.guild = MagicMock(spec=discord.Guild)
    now = datetime.now(ZoneInfo("UTC"))
    events = [_event_schema(name="Upcoming 1"), _event_schema(name="Upcoming 2")]
    timeline = {"Upcoming 1": now + timedelta(hours=1), "Upcoming 2": now + timedelta(hours=2)}

    cog._resolve_org_id = AsyncMock(return_value="org-1")  # type: ignore[method-assign]
    cog._fetch_backend_events = AsyncMock(return_value=events)  # type: ignore[method-assign]
    cog._event_datetime = MagicMock(side_effect=lambda event: timeline[event.event_name])  # type: ignore[method-assign]
    cog._is_user_registered = AsyncMock(return_value=False)  # type: ignore[method-assign]

    await cog.handle_myevents_action(interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Your Registered Events"
    assert "haven't registered" in (embed.description or "")


@pytest.mark.asyncio
async def test_handle_myevents_action_registered_events_sorted(cog: Event, interaction: MagicMock) -> None:
    interaction.guild = MagicMock(spec=discord.Guild)
    now = datetime.now(ZoneInfo("UTC"))
    events = [_event_schema(name="Past"), _event_schema(name="Soon"), _event_schema(name="Later")]
    timeline = {
        "Past": now - timedelta(hours=1),
        "Soon": now + timedelta(minutes=30),
        "Later": now + timedelta(hours=3),
    }

    async def _is_registered(event: EventSchema, _guild: discord.Guild, _user: discord.User) -> bool:
        return event.event_name in {"Soon", "Later"}

    cog._resolve_org_id = AsyncMock(return_value="org-1")  # type: ignore[method-assign]
    cog._fetch_backend_events = AsyncMock(return_value=events)  # type: ignore[method-assign]
    cog._event_datetime = MagicMock(side_effect=lambda event: timeline[event.event_name])  # type: ignore[method-assign]
    cog._is_user_registered = AsyncMock(side_effect=_is_registered)  # type: ignore[method-assign]

    await cog.handle_myevents_action(interaction)

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert [field.name for field in embed.fields] == ["Soon", "Later"]


@pytest.mark.asyncio
async def test_on_announce_select_member_cache_unavailable(cog: Event, interaction: MagicMock) -> None:
    guild = _guild(guild_id=interaction.guild_id)
    guild.me = None
    interaction.guild = guild
    interaction.response.is_done = MagicMock(return_value=False)

    channel = MagicMock(spec=discord.TextChannel)
    cog._get_announcement_channel = MagicMock(return_value=channel)  # type: ignore[method-assign]
    object.__setattr__(cog.bot, "user", None)

    await cog._on_announce_select(interaction, _event_schema(name="Announce", event_id="evt-1"))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Member Cache Unavailable"


@pytest.mark.asyncio
async def test_on_announce_select_no_send_permission(cog: Event, interaction: MagicMock) -> None:
    guild = _guild(guild_id=interaction.guild_id)
    bot_member = MagicMock()
    guild.me = bot_member
    interaction.guild = guild
    interaction.response.is_done = MagicMock(return_value=False)

    permissions = MagicMock()
    permissions.send_messages = False

    channel = MagicMock(spec=discord.TextChannel)
    channel.permissions_for = MagicMock(return_value=permissions)
    cog._get_announcement_channel = MagicMock(return_value=channel)  # type: ignore[method-assign]

    await cog._on_announce_select(interaction, _event_schema(name="Announce", event_id="evt-1"))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "No Permission"


@pytest.mark.asyncio
async def test_is_user_registered_returns_false_when_no_message_id(cog: Event) -> None:
    guild = _guild()
    user = MagicMock(spec=discord.User)

    result = await cog._is_user_registered(_event_schema(name="Missing Message"), guild, user)

    assert result is False


@pytest.mark.asyncio
async def test_respond_from_modal_edit_failure_falls_back_to_send_message(cog: Event, interaction: MagicMock) -> None:
    interaction.message = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.edit_message = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))

    embed = discord.Embed(title="Fallback Test")
    await cog._respond_from_modal(interaction, embed)

    interaction.response.edit_message.assert_awaited_once()
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_delete_select_no_guild_id_returns_error(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ConfirmDeleteViewStub:
        def __init__(self) -> None:
            self.value = True

        async def wait(self) -> None:
            return None

    interaction.guild_id = None
    monkeypatch.setattr("capy_discord.exts.event.event.ConfirmDeleteView", _ConfirmDeleteViewStub)

    await cog._on_delete_select(interaction, _event_schema(name="Delete Me", event_id="evt-42"))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Error"


@pytest.mark.asyncio
async def test_on_delete_select_missing_event_id_returns_error(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ConfirmDeleteViewStub:
        def __init__(self) -> None:
            self.value = True

        async def wait(self) -> None:
            return None

    monkeypatch.setattr("capy_discord.exts.event.event.ConfirmDeleteView", _ConfirmDeleteViewStub)

    await cog._on_delete_select(interaction, _event_schema(name="Delete Me", event_id=None))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Event Not Found"


@pytest.mark.asyncio
async def test_on_delete_select_backend_error_returns_failure(
    cog: Event,
    interaction: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ConfirmDeleteViewStub:
        def __init__(self) -> None:
            self.value = True

        async def wait(self) -> None:
            return None

    client = MagicMock()
    client.delete_event = AsyncMock(side_effect=BackendAPIError("boom", status_code=500))

    monkeypatch.setattr("capy_discord.exts.event.event.ConfirmDeleteView", _ConfirmDeleteViewStub)
    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    await cog._on_delete_select(interaction, _event_schema(name="Delete Me", event_id="evt-42"))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Failed to Delete"


@pytest.mark.asyncio
async def test_fetch_backend_events_skips_malformed_event(cog: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.list_events_by_organization = AsyncMock(
        return_value=[
            _backend_event(eid="evt-good", title="Good", event_time="2026-04-14T14:00:00Z", org_id="org-1"),
            _backend_event(eid="evt-bad", title="Bad", event_time="not-a-time", org_id="org-1"),
        ]
    )
    client.list_organization_events = AsyncMock()
    client.list_events = AsyncMock()

    monkeypatch.setattr("capy_discord.exts.event.event.get_database_pool", lambda: client)

    events = await cog._fetch_backend_events("org-1")

    assert [event.event_id for event in events] == ["evt-good"]


@pytest.mark.asyncio
async def test_on_announce_select_forbidden_returns_permission_denied(cog: Event, interaction: MagicMock) -> None:
    guild = _guild(guild_id=interaction.guild_id)
    interaction.guild = guild
    interaction.response.is_done = MagicMock(return_value=False)

    bot_member = MagicMock()
    guild.me = bot_member

    permissions = MagicMock()
    permissions.send_messages = True

    channel = MagicMock(spec=discord.TextChannel)
    channel.permissions_for = MagicMock(return_value=permissions)
    channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "forbidden"))
    cog._get_announcement_channel = MagicMock(return_value=channel)  # type: ignore[method-assign]

    await cog._on_announce_select(interaction, _event_schema(name="Announce", event_id="evt-1"))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Permission Denied"


@pytest.mark.asyncio
async def test_on_announce_select_http_exception_returns_failure(cog: Event, interaction: MagicMock) -> None:
    guild = _guild(guild_id=interaction.guild_id)
    interaction.guild = guild
    interaction.response.is_done = MagicMock(return_value=False)

    bot_member = MagicMock()
    guild.me = bot_member

    permissions = MagicMock()
    permissions.send_messages = True

    channel = MagicMock(spec=discord.TextChannel)
    channel.permissions_for = MagicMock(return_value=permissions)
    channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "http boom"))
    cog._get_announcement_channel = MagicMock(return_value=channel)  # type: ignore[method-assign]

    await cog._on_announce_select(interaction, _event_schema(name="Announce", event_id="evt-1"))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "Announcement Failed"


@pytest.mark.asyncio
async def test_event_dropdown_select_callback_sets_selection(cog: Event, interaction: MagicMock) -> None:
    events = [_event_schema(name="Option 1"), _event_schema(name="Option 2")]
    view = EventDropdownView(events, cog, "Pick", AsyncMock())
    select = next(item for item in view.children if isinstance(item, EventDropdownSelect))
    select._values = ["1"]

    await select.callback(interaction)

    assert view.selected_event_idx == 1
    assert view.confirm.disabled is False
    interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_event_dropdown_confirm_without_selection_shows_error(cog: Event, interaction: MagicMock) -> None:
    view = EventDropdownView([_event_schema(name="Option 1")], cog, "Pick", AsyncMock())
    confirm_button = next(
        item for item in view.children if isinstance(item, discord.ui.Button) and item.label == "Confirm"
    )

    await confirm_button.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.title == "No Selection"


@pytest.mark.asyncio
async def test_event_dropdown_cancel_sets_cancelled(cog: Event, interaction: MagicMock) -> None:
    view = EventDropdownView([_event_schema(name="Option 1")], cog, "Pick", AsyncMock())
    cancel_button = next(
        item for item in view.children if isinstance(item, discord.ui.Button) and item.label == "Cancel"
    )

    await cancel_button.callback(interaction)

    assert view.cancelled is True
    interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_delete_view_buttons_set_value(interaction: MagicMock) -> None:
    view = ConfirmDeleteView()
    delete_button = next(
        item for item in view.children if isinstance(item, discord.ui.Button) and item.label == "Delete"
    )
    await delete_button.callback(interaction)
    assert view.value is True

    interaction.response.edit_message.reset_mock()
    view2 = ConfirmDeleteView()
    cancel_button = next(
        item for item in view2.children if isinstance(item, discord.ui.Button) and item.label == "Cancel"
    )
    await cancel_button.callback(interaction)
    assert view2.value is False


@pytest.mark.asyncio
async def test_setup_adds_event_cog(bot: MagicMock) -> None:
    bot.add_cog = AsyncMock()

    await setup(bot)

    bot.add_cog.assert_awaited_once()
    added_cog = bot.add_cog.await_args_list[0].args[0]
    assert isinstance(added_cog, Event)
