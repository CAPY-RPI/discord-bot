from unittest.mock import AsyncMock, patch

import pytest

from capy_discord.database import (
    BackendAPIError,
    BackendClientConfig,
    BackendClientNotInitializedError,
    HTTP_STATUS_NOT_FOUND,
    close_database_pool,
    get_database_pool,
    init_database_pool,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | list | None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"" if payload is None else b"payload"

    def json(self):
        if self._payload is None:
            msg = "No JSON payload available"
            raise ValueError(msg)
        return self._payload


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
@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_list_events_makes_expected_request(mock_request):
    await close_database_pool()
    mock_request.return_value = _FakeResponse(200, [{"eid": "evt-1", "description": "hello"}])

    client = await init_database_pool("http://localhost:8080", config=BackendClientConfig())
    events = await client.list_events(limit=10, offset=5)

    assert events[0].get("eid") == "evt-1"
    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["url"] == "/events"
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
    assert register_kwargs["url"] == "/events/evt-1/register"
    assert register_kwargs["json"] == {"uid": "user-1", "is_attending": True}

    assert unregister_kwargs["method"] == "DELETE"
    assert unregister_kwargs["url"] == "/events/evt-1/register"
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
