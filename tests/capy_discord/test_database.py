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
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_CREATED,
    HTTP_STATUS_NOT_FOUND,
    _normalize_api_base_url,
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

    with pytest.raises(BackendConfigurationError, match="base_url must be set"):
        _normalize_api_base_url("   ")


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
async def test_auth_redirect_does_not_require_json_payload(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeInvalidJsonResponse(302)

    client = await init_database_pool("http://localhost:8080")
    await client.auth_google_redirect()

    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["url"] == "auth/google"

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_auth_callback_uses_query_params(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeInvalidJsonResponse(302)

    client = await init_database_pool("http://localhost:8080")
    await client.auth_google_callback(code="abc", state="xyz")

    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["url"] == "auth/google/callback"
    assert kwargs["params"] == {"code": "abc", "state": "xyz"}

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_auth_microsoft_redirect_and_callback(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeInvalidJsonResponse(302),
        _FakeInvalidJsonResponse(302),
    ]

    client = await init_database_pool("http://localhost:8080")
    await client.auth_microsoft_redirect()
    await client.auth_microsoft_callback(code="mcode", state="mstate")

    first_kwargs = mock_request.await_args_list[0].kwargs
    second_kwargs = mock_request.await_args_list[1].kwargs

    assert first_kwargs["url"] == "auth/microsoft"
    assert second_kwargs["url"] == "auth/microsoft/callback"
    assert second_kwargs["params"] == {"code": "mcode", "state": "mstate"}

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_auth_logout_uses_no_content_status(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(204, None)

    client = await init_database_pool("http://localhost:8080")
    await client.auth_logout()

    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "auth/logout"

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_auth_me_and_refresh_return_expected_payloads(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(200, {"uid": "u-1", "email": "user@example.com"}),
        _FakeResponse(200, {"token": "jwt", "user": {"uid": "u-1"}}),
    ]

    client = await init_database_pool("http://localhost:8080")
    me = await client.auth_me()
    refreshed = await client.auth_refresh()

    assert me.get("uid") == "u-1"
    assert refreshed.get("token") == "jwt"

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_auth_callback_bad_request_raises_backend_api_error(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(HTTP_STATUS_BAD_REQUEST, {"message": "invalid callback"})

    client = await init_database_pool("http://localhost:8080")

    with pytest.raises(BackendAPIError) as exc_info:
        await client.auth_google_callback(code="bad", state="bad")

    assert exc_info.value.status_code == HTTP_STATUS_BAD_REQUEST

    await close_database_pool()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_bot_endpoints_use_expected_paths(mock_request):
    await close_database_pool()
    mock_request.side_effect = [
        _FakeResponse(200, {"token_id": "t-1", "name": "bot-token"}),
        _FakeResponse(200, [{"token_id": "t-1"}]),
        _FakeResponse(HTTP_STATUS_CREATED, {"token_id": "t-2", "token": "secret"}),
        _FakeResponse(204, None),
    ]

    client = await init_database_pool("http://localhost:8080")
    me = await client.bot_me()
    tokens = await client.list_bot_tokens()
    created = await client.create_bot_token({"name": "new-token"})
    await client.revoke_bot_token("t-2")

    assert me.get("token_id") == "t-1"
    assert tokens[0].get("token_id") == "t-1"
    assert created.get("token_id") == "t-2"

    first_kwargs = mock_request.await_args_list[0].kwargs
    second_kwargs = mock_request.await_args_list[1].kwargs
    third_kwargs = mock_request.await_args_list[2].kwargs
    fourth_kwargs = mock_request.await_args_list[3].kwargs

    assert first_kwargs["url"] == "bot/me"
    assert second_kwargs["url"] == "bot/tokens"
    assert third_kwargs["url"] == "bot/tokens"
    assert third_kwargs["json"] == {"name": "new-token"}
    assert fourth_kwargs["url"] == "bot/tokens/t-2"

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
