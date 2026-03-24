import asyncio
import secrets
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from capy_discord.database import (
    BackendAPIClient,
    BackendAPIError,
    BackendClientConfig,
    BackendClientNotInitializedError,
    BackendConfigurationError,
    HTTP_STATUS_CREATED,
    HTTP_STATUS_NOT_FOUND,
    _normalize_api_base_url,
    _normalize_request_path,
    close_database_pool,
    get_database_pool,
    init_database_pool,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | list | str | None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"" if payload is None else b"payload"

    def json(self):
        if self._payload is None:
            msg = "No JSON payload available"
            raise ValueError(msg)
        return self._payload


class _FakeInvalidJsonResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.content = b"not-json"

    def json(self):
        msg = "Invalid JSON payload"
        raise ValueError(msg)


@pytest.mark.asyncio
async def test_client_configuration_validation_errors():
    with pytest.raises(BackendConfigurationError, match="base_url must be set"):
        BackendAPIClient("")

    with pytest.raises(ValueError, match="timeout_seconds must be greater than 0"):
        BackendAPIClient("http://localhost:8080", config=BackendClientConfig(timeout_seconds=0))

    with pytest.raises(ValueError, match="max_connections must be at least 1"):
        BackendAPIClient("http://localhost:8080", config=BackendClientConfig(max_connections=0))

    with pytest.raises(ValueError, match="max_keepalive_connections must be at least 0"):
        BackendAPIClient("http://localhost:8080", config=BackendClientConfig(max_keepalive_connections=-1))


@pytest.mark.asyncio
async def test_unstarted_client_raises_not_initialized_error():
    client = BackendAPIClient("http://localhost:8080")

    with pytest.raises(BackendClientNotInitializedError):
        await client.list_events()


def test_normalize_api_base_url_behaviors():
    assert _normalize_api_base_url("http://localhost:8080") == "http://localhost:8080/v1/"
    assert _normalize_api_base_url("http://localhost:8080/") == "http://localhost:8080/v1/"
    assert _normalize_api_base_url("https://api.example.com/v1") == "https://api.example.com/v1/"
    assert _normalize_api_base_url("http://localhost:8080/api/v1/bot") == "http://localhost:8080/api/v1/bot/"

    with pytest.raises(BackendConfigurationError, match="base_url must be set"):
        _normalize_api_base_url("   ")


def test_normalize_request_path_handles_absolute_urls_and_relative_paths():
    assert (
        _normalize_request_path("https://api.example.com/api/v1/bot/events")
        == "https://api.example.com/api/v1/bot/events"
    )
    assert _normalize_request_path("http://localhost:8080/health") == "http://localhost:8080/health"
    assert _normalize_request_path("/bot/events") == "bot/events"
    assert _normalize_request_path("bot/events") == "bot/events"


@pytest.mark.asyncio
async def test_client_config_applies_bot_token_and_cookie():
    bot_token_value = secrets.token_urlsafe(12)
    auth_cookie_value = secrets.token_urlsafe(12)

    client = BackendAPIClient(
        "http://localhost:8080",
        config=BackendClientConfig(bot_token=bot_token_value, auth_cookie=auth_cookie_value),
    )
    await client.start()

    assert client._client.headers.get("X-Bot-Token") == bot_token_value
    assert client._client.cookies.get("capy_auth") == auth_cookie_value

    await client.close()


@pytest.mark.asyncio
async def test_get_database_pool_requires_initialization():
    await close_database_pool()

    with pytest.raises(BackendClientNotInitializedError):
        get_database_pool()


@pytest.mark.asyncio
async def test_init_database_pool_is_idempotent():
    await close_database_pool()

    first = await init_database_pool("http://localhost:8080")
    second = await init_database_pool("http://localhost:9000")

    assert first is second
    assert first is get_database_pool()

    await close_database_pool()


@pytest.mark.asyncio
async def test_init_database_pool_recreates_stopped_cached_client():
    await close_database_pool()

    first = await init_database_pool("http://localhost:8080")
    await first.close()

    second = await init_database_pool("http://localhost:8080")

    assert first is not second
    assert second.is_started is True
    assert second is get_database_pool()

    await close_database_pool()


@pytest.mark.asyncio
async def test_init_database_pool_concurrent_calls_share_single_instance():
    await close_database_pool()

    first, second = await asyncio.gather(
        init_database_pool("http://localhost:8080"),
        init_database_pool("http://localhost:8080"),
    )

    assert first is second
    assert first is get_database_pool()

    await close_database_pool()


@pytest.mark.asyncio
async def test_close_and_init_race_does_not_leave_pool_unusable():
    await close_database_pool()

    for _ in range(20):
        await asyncio.gather(
            init_database_pool("http://localhost:8080"),
            close_database_pool(),
        )

    client = await init_database_pool("http://localhost:8080")
    assert client.is_started is True
    assert get_database_pool().is_started is True

    await close_database_pool()


@pytest.mark.asyncio
async def test_get_database_pool_can_return_stopped_cached_client():
    await close_database_pool()

    client = await init_database_pool("http://localhost:8080")
    await client.close()

    cached = get_database_pool()
    assert cached is client
    assert cached.is_started is False

    await close_database_pool()


@pytest.mark.asyncio
async def test_close_database_pool_is_idempotent():
    await close_database_pool()
    await init_database_pool("http://localhost:8080")

    await close_database_pool()
    await close_database_pool()

    with pytest.raises(BackendClientNotInitializedError):
        get_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_list_events_makes_expected_request(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(200, [{"eid": "evt-1", "description": "hello"}])

    client = await init_database_pool("http://localhost:8080", config=BackendClientConfig())
    events = await client.list_events(limit=10, offset=5)

    assert events[0].get("eid") == "evt-1"
    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["url"] == "events"
    assert kwargs["params"] == {"limit": 10, "offset": 5}

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_register_and_unregister_event_use_expected_status_codes(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(201, None),
        _FakeResponse(204, None),
    ]

    client = await init_database_pool("http://localhost:8080")
    await client.register_event("evt-1", {"uid": "user-1", "is_attending": True})
    await client.unregister_event("evt-1", uid="user-1")

    register_kwargs = mock_request.await_args_list[0].kwargs
    unregister_kwargs = mock_request.await_args_list[1].kwargs

    assert register_kwargs["method"] == "POST"
    assert register_kwargs["url"] == "events/evt-1/register"
    assert register_kwargs["json"] == {"uid": "user-1", "is_attending": True}

    assert unregister_kwargs["method"] == "DELETE"
    assert unregister_kwargs["url"] == "events/evt-1/register"
    assert unregister_kwargs["params"] == {"uid": "user-1"}

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_backend_error_is_raised_with_status_and_payload(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(HTTP_STATUS_NOT_FOUND, {"error": "not_found", "message": "event missing"})

    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(BackendAPIError) as exc_info:
        await client.get_event("missing")

    assert exc_info.value.status_code == HTTP_STATUS_NOT_FOUND
    assert exc_info.value.payload == {"error": "not_found", "message": "event missing"}

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_list_events_by_organization_uses_swagger_path(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(200, [{"eid": "evt-2"}])

    client = await init_database_pool("http://localhost:8080")
    events = await client.list_events_by_organization("org-1", limit=20, offset=0)

    assert events[0].get("eid") == "evt-2"
    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["url"] == "events/org/org-1"
    assert kwargs["params"] == {"limit": 20, "offset": 0}

    await close_database_pool()


@pytest.mark.asyncio
async def test_list_events_rejects_invalid_pagination_values():
    await close_database_pool()
    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(ValueError, match="limit must be at least 1"):
        await client.list_events(limit=0)

    with pytest.raises(ValueError, match="offset must be at least 0"):
        await client.list_events(offset=-1)

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_invalid_json_response_raises_backend_api_error(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeInvalidJsonResponse(200)

    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(BackendAPIError) as exc_info:
        await client.list_events()

    assert exc_info.value.status_code == 200

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_non_json_error_response_uses_status_fallback_message(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeInvalidJsonResponse(502)

    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(BackendAPIError) as exc_info:
        await client.get_event("evt-1")

    assert exc_info.value.status_code == 502
    assert exc_info.value.payload is None
    assert "status 502" in str(exc_info.value)

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_request_without_response_body_handles_non_json_payload(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeInvalidJsonResponse(HTTP_STATUS_CREATED)

    client = BackendAPIClient("http://localhost:8080")
    await client.start()

    await client._request_without_response_body("POST", "/bot/events", expected_statuses={HTTP_STATUS_CREATED})

    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "bot/events"

    await client.close()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_request_without_response_body_raises_on_unexpected_status(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(HTTP_STATUS_NOT_FOUND, {"message": "missing"})

    client = BackendAPIClient("http://localhost:8080")
    await client.start()

    with pytest.raises(BackendAPIError) as exc_info:
        await client._request_without_response_body("GET", "/bot/events", expected_statuses={HTTP_STATUS_CREATED})

    assert exc_info.value.status_code == HTTP_STATUS_NOT_FOUND

    await client.close()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_bot_me_endpoint_uses_expected_path(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(200, {"token_id": "t-1", "name": "bot-token"})

    client = await init_database_pool("http://localhost:8080")
    me = await client.bot_me()

    assert me.get("token_id") == "t-1"

    kwargs = mock_request.call_args.kwargs
    assert kwargs["url"] == "me"

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_organization_endpoints_use_expected_paths(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(200, [{"oid": "org-1", "name": "Org One"}]),
        _FakeResponse(200, {"oid": "org-1", "name": "Org One"}),
        _FakeResponse(HTTP_STATUS_CREATED, {"oid": "org-2", "name": "Org Two"}),
        _FakeResponse(200, {"oid": "org-2", "name": "Org Two Updated"}),
        _FakeResponse(204, None),
        _FakeResponse(200, [{"eid": "evt-1"}]),
    ]

    client = await init_database_pool("http://localhost:8080")
    organizations = await client.list_organizations(limit=5, offset=0)
    organization = await client.get_organization("org-1")
    created = await client.create_organization({"name": "Org Two"})
    updated = await client.update_organization("org-2", {"name": "Org Two Updated"})
    await client.delete_organization("org-2")
    org_events = await client.list_organization_events("org-1", limit=5, offset=0)

    assert organizations[0].get("oid") == "org-1"
    assert organization.get("name") == "Org One"
    assert created.get("oid") == "org-2"
    assert updated.get("name") == "Org Two Updated"
    assert org_events[0].get("eid") == "evt-1"

    list_kwargs = mock_request.await_args_list[0].kwargs
    assert list_kwargs["url"] == "organizations"
    assert list_kwargs["params"] == {"limit": 5, "offset": 0}

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_event_crud_and_registration_endpoints(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(200, {"eid": "evt-1", "location": "DCC"}),
        _FakeResponse(HTTP_STATUS_CREATED, {"eid": "evt-2", "location": "DCC"}),
        _FakeResponse(200, {"eid": "evt-2", "location": "CBIS"}),
        _FakeResponse(204, None),
        _FakeResponse(200, [{"uid": "user-1", "is_attending": True}]),
    ]

    client = await init_database_pool("http://localhost:8080")
    fetched = await client.get_event("evt-1")
    created = await client.create_event({"org_id": "org-1", "location": "DCC"})
    updated = await client.update_event("evt-2", {"location": "CBIS"})
    await client.delete_event("evt-2")
    registrations = await client.list_event_registrations("evt-1")

    assert fetched.get("eid") == "evt-1"
    assert created.get("eid") == "evt-2"
    assert updated.get("location") == "CBIS"
    assert registrations[0].get("uid") == "user-1"

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_partial_success_payloads_do_not_crash_typed_dict_or_list(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(200, {}),
        _FakeResponse(HTTP_STATUS_CREATED, {"location": "DCC"}),
        _FakeResponse(200, [{}]),
    ]

    client = await init_database_pool("http://localhost:8080")
    bot_info = await client.bot_me()
    event = await client.create_event({"org_id": "org-1", "location": "DCC"})
    events = await client.list_events()

    assert bot_info == {}
    assert event.get("location") == "DCC"
    assert events == [{}]

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_http_transport_error_maps_to_backend_api_error(mock_request):
    await close_database_pool()
    mock_request.side_effect = httpx.ConnectError("boom")

    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(BackendAPIError) as exc_info:
        await client.list_events()

    assert exc_info.value.status_code == 0

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_unexpected_scalar_payload_raises_backend_api_error(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(200, "not-a-json-object")

    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(BackendAPIError):
        await client.list_events()

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_list_payload_with_non_object_entries_raises_backend_api_error(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(200, ["bad-item"])

    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(BackendAPIError):
        await client.list_events()

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_organization_member_endpoints_use_expected_paths(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(200, [{"uid": "user-1", "is_admin": True}]),
        _FakeResponse(201, None),
        _FakeResponse(204, None),
    ]

    client = await init_database_pool("http://localhost:8080")
    members = await client.list_organization_members("org-1")
    await client.add_organization_member("org-1", {"uid": "user-2", "is_admin": False})
    await client.remove_organization_member("org-1", "user-2")

    assert members[0].get("uid") == "user-1"

    list_kwargs = mock_request.await_args_list[0].kwargs
    add_kwargs = mock_request.await_args_list[1].kwargs
    remove_kwargs = mock_request.await_args_list[2].kwargs

    assert list_kwargs["url"] == "organizations/org-1/members"
    assert add_kwargs["url"] == "organizations/org-1/members"
    assert add_kwargs["json"] == {"uid": "user-2", "is_admin": False}
    assert remove_kwargs["url"] == "organizations/org-1/members/user-2"

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_user_endpoints_use_expected_paths(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(200, {"uid": "user-1", "first_name": "Ada"}),
        _FakeResponse(200, {"uid": "user-1", "first_name": "Grace"}),
        _FakeResponse(204, None),
        _FakeResponse(200, [{"eid": "evt-1"}]),
        _FakeResponse(200, [{"oid": "org-1"}]),
    ]

    client = await init_database_pool("http://localhost:8080")
    user = await client.get_user("user-1")
    updated = await client.update_user("user-1", {"first_name": "Grace"})
    await client.delete_user("user-1")
    events = await client.list_user_events("user-1")
    organizations = await client.list_user_organizations("user-1")

    assert user.get("first_name") == "Ada"
    assert updated.get("first_name") == "Grace"
    assert events[0].get("eid") == "evt-1"
    assert organizations[0].get("oid") == "org-1"

    get_kwargs = mock_request.await_args_list[0].kwargs
    update_kwargs = mock_request.await_args_list[1].kwargs
    delete_kwargs = mock_request.await_args_list[2].kwargs

    assert get_kwargs["url"] == "users/user-1"
    assert update_kwargs["url"] == "users/user-1"
    assert update_kwargs["json"] == {"first_name": "Grace"}
    assert delete_kwargs["url"] == "users/user-1"

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.aclose", new_callable=AsyncMock)
async def test_async_context_manager_starts_and_closes_client(mock_aclose):
    await close_database_pool()

    async with await init_database_pool("http://localhost:8080") as client:
        assert client.is_started is True

    assert mock_aclose.await_count >= 1

    await close_database_pool()
