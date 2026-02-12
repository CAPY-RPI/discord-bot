from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, NotRequired, Required, TypedDict, cast

import httpx

HTTP_STATUS_OK = 200
HTTP_STATUS_CREATED = 201
HTTP_STATUS_NO_CONTENT = 204
HTTP_STATUS_NOT_FOUND = 404


class BackendConfigurationError(RuntimeError):
    """Raised when backend client settings are invalid."""


class BackendClientNotInitializedError(RuntimeError):
    """Raised when the backend client is accessed before initialization."""


class BackendAPIError(RuntimeError):
    """Raised when the backend API returns an error response."""

    def __init__(self, message: str, *, status_code: int, payload: dict[str, Any] | None = None) -> None:
        """Initialize backend API error details."""
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ErrorResponse(TypedDict):
    """Represents backend API error payloads."""

    error: NotRequired[str]
    message: NotRequired[str]


class CreateBotTokenRequest(TypedDict, total=False):
    """Represents request payload for creating a bot token."""

    name: Required[str]
    expires_at: str


class BotTokenResponse(TypedDict, total=False):
    """Represents bot token response payloads."""

    token_id: str
    name: str
    token: str
    is_active: bool
    created_at: str
    expires_at: str


class CreateEventRequest(TypedDict, total=False):
    """Represents event creation payloads."""

    org_id: Required[str]
    description: str
    event_time: str
    location: str


class UpdateEventRequest(TypedDict, total=False):
    """Represents event update payloads."""

    description: str
    event_time: str
    location: str


class RegisterEventRequest(TypedDict, total=False):
    """Represents event registration payloads."""

    uid: str
    is_attending: bool


class EventResponse(TypedDict, total=False):
    """Represents event response payloads."""

    eid: str
    description: str
    event_time: str
    location: str
    date_created: str
    date_modified: str


class EventRegistrationResponse(TypedDict, total=False):
    """Represents event registration response payloads."""

    uid: str
    first_name: str
    last_name: str
    is_attending: bool
    is_admin: bool
    date_registered: str


class CreateOrganizationRequest(TypedDict, total=False):
    """Represents organization creation payloads."""

    name: Required[str]
    creator_uid: str


class UpdateOrganizationRequest(TypedDict, total=False):
    """Represents organization update payloads."""

    name: str


class OrganizationResponse(TypedDict, total=False):
    """Represents organization response payloads."""

    oid: str
    name: str
    date_created: str
    date_modified: str


@dataclass(slots=True)
class BackendClientConfig:
    """Configures authentication and pooling for backend API calls."""

    bot_token: str = ""
    auth_cookie: str = ""
    timeout_seconds: float = 10.0
    max_connections: int = 20
    max_keepalive_connections: int = 10


class BackendAPIClient:
    """HTTP client for backend routes exposed through Swagger."""

    def __init__(
        self,
        base_url: str,
        config: BackendClientConfig | None = None,
    ) -> None:
        """Initialize an HTTP client configured for backend API calls."""
        client_config = config or BackendClientConfig()

        if not base_url:
            msg = "base_url must be set"
            raise BackendConfigurationError(msg)
        if client_config.timeout_seconds <= 0:
            msg = "timeout_seconds must be greater than 0"
            raise ValueError(msg)
        if client_config.max_connections < 1:
            msg = "max_connections must be at least 1"
            raise ValueError(msg)
        if client_config.max_keepalive_connections < 0:
            msg = "max_keepalive_connections must be at least 0"
            raise ValueError(msg)

        api_base_url = _normalize_api_base_url(base_url)
        headers: dict[str, str] = {"Accept": "application/json"}
        cookies: dict[str, str] = {}
        if client_config.bot_token:
            headers["X-Bot-Token"] = client_config.bot_token
        if client_config.auth_cookie:
            cookies["capy_auth"] = client_config.auth_cookie

        self._client = httpx.AsyncClient(
            base_url=api_base_url,
            headers=headers,
            cookies=cookies,
            timeout=httpx.Timeout(client_config.timeout_seconds),
            limits=httpx.Limits(
                max_connections=client_config.max_connections,
                max_keepalive_connections=client_config.max_keepalive_connections,
            ),
        )
        self._started = False

    async def start(self) -> None:
        """Mark the client as ready for request execution."""
        self._started = True

    async def close(self) -> None:
        """Close pooled HTTP connections."""
        if not self._started:
            return

        await self._client.aclose()
        self._started = False

    async def bot_me(self) -> BotTokenResponse:
        """Call `GET /bot/me`."""
        payload = await self._request("GET", "/bot/me")
        return cast("BotTokenResponse", _typed_dict(payload))

    async def list_bot_tokens(self) -> list[BotTokenResponse]:
        """Call `GET /bot/tokens`."""
        payload = await self._request("GET", "/bot/tokens")
        return cast("list[BotTokenResponse]", _typed_list(payload))

    async def create_bot_token(self, data: CreateBotTokenRequest) -> BotTokenResponse:
        """Call `POST /bot/tokens`."""
        payload = await self._request("POST", "/bot/tokens", json_body=data, expected_statuses={HTTP_STATUS_CREATED})
        return cast("BotTokenResponse", _typed_dict(payload))

    async def revoke_bot_token(self, token_id: str) -> None:
        """Call `DELETE /bot/tokens/{token_id}`."""
        await self._request("DELETE", f"/bot/tokens/{token_id}", expected_statuses={HTTP_STATUS_NO_CONTENT})

    async def list_events(self, *, limit: int | None = None, offset: int | None = None) -> list[EventResponse]:
        """Call `GET /events`."""
        params = _optional_params(limit=limit, offset=offset)
        payload = await self._request("GET", "/events", params=params)
        return cast("list[EventResponse]", _typed_list(payload))

    async def get_event(self, event_id: str) -> EventResponse:
        """Call `GET /events/{eid}`."""
        payload = await self._request("GET", f"/events/{event_id}")
        return cast("EventResponse", _typed_dict(payload))

    async def create_event(self, data: CreateEventRequest) -> EventResponse:
        """Call `POST /events`."""
        payload = await self._request("POST", "/events", json_body=data, expected_statuses={HTTP_STATUS_CREATED})
        return cast("EventResponse", _typed_dict(payload))

    async def update_event(self, event_id: str, data: UpdateEventRequest) -> EventResponse:
        """Call `PUT /events/{eid}`."""
        payload = await self._request("PUT", f"/events/{event_id}", json_body=data)
        return cast("EventResponse", _typed_dict(payload))

    async def delete_event(self, event_id: str) -> None:
        """Call `DELETE /events/{eid}`."""
        await self._request("DELETE", f"/events/{event_id}", expected_statuses={HTTP_STATUS_NO_CONTENT})

    async def register_event(self, event_id: str, data: RegisterEventRequest) -> None:
        """Call `POST /events/{eid}/register`."""
        await self._request(
            "POST",
            f"/events/{event_id}/register",
            json_body=data,
            expected_statuses={HTTP_STATUS_CREATED},
        )

    async def unregister_event(self, event_id: str, *, uid: str | None = None) -> None:
        """Call `DELETE /events/{eid}/register`."""
        params = _optional_params(uid=uid)
        await self._request(
            "DELETE",
            f"/events/{event_id}/register",
            params=params,
            expected_statuses={HTTP_STATUS_NO_CONTENT},
        )

    async def list_event_registrations(self, event_id: str) -> list[EventRegistrationResponse]:
        """Call `GET /events/{eid}/registrations`."""
        payload = await self._request("GET", f"/events/{event_id}/registrations")
        return cast("list[EventRegistrationResponse]", _typed_list(payload))

    async def list_organizations(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[OrganizationResponse]:
        """Call `GET /organizations`."""
        params = _optional_params(limit=limit, offset=offset)
        payload = await self._request("GET", "/organizations", params=params)
        return cast("list[OrganizationResponse]", _typed_list(payload))

    async def get_organization(self, organization_id: str) -> OrganizationResponse:
        """Call `GET /organizations/{oid}`."""
        payload = await self._request("GET", f"/organizations/{organization_id}")
        return cast("OrganizationResponse", _typed_dict(payload))

    async def create_organization(self, data: CreateOrganizationRequest) -> OrganizationResponse:
        """Call `POST /organizations`."""
        payload = await self._request("POST", "/organizations", json_body=data, expected_statuses={HTTP_STATUS_CREATED})
        return cast("OrganizationResponse", _typed_dict(payload))

    async def update_organization(self, organization_id: str, data: UpdateOrganizationRequest) -> OrganizationResponse:
        """Call `PUT /organizations/{oid}`."""
        payload = await self._request("PUT", f"/organizations/{organization_id}", json_body=data)
        return cast("OrganizationResponse", _typed_dict(payload))

    async def delete_organization(self, organization_id: str) -> None:
        """Call `DELETE /organizations/{oid}`."""
        await self._request("DELETE", f"/organizations/{organization_id}", expected_statuses={HTTP_STATUS_NO_CONTENT})

    async def list_organization_events(
        self,
        organization_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[EventResponse]:
        """Call `GET /organizations/{oid}/events`."""
        params = _optional_params(limit=limit, offset=offset)
        payload = await self._request("GET", f"/organizations/{organization_id}/events", params=params)
        return cast("list[EventResponse]", _typed_list(payload))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: object | None = None,
        expected_statuses: set[int] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Execute a backend API request and enforce expected status codes."""
        self._ensure_started()
        statuses = expected_statuses or {HTTP_STATUS_OK}

        try:
            response = await self._client.request(method=method, url=path, params=params, json=json_body)
        except httpx.HTTPError as exc:
            msg = f"HTTP request failed for {method} {path}"
            raise BackendAPIError(msg, status_code=0) from exc

        if response.status_code not in statuses:
            raise _to_backend_api_error(response)

        if response.status_code == HTTP_STATUS_NO_CONTENT:
            return None

        if not response.content:
            return None

        payload = response.json()
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        msg = f"Unexpected response payload for {method} {path}"
        raise BackendAPIError(msg, status_code=response.status_code)

    def _ensure_started(self) -> None:
        if self._started:
            return

        msg = "Backend client has not been initialized"
        raise BackendClientNotInitializedError(msg)


class _ClientState:
    def __init__(self) -> None:
        self.client: BackendAPIClient | None = None


_client_state = _ClientState()
_client_lock = asyncio.Lock()


async def init_database_pool(
    database_url: str,
    *,
    config: BackendClientConfig | None = None,
) -> BackendAPIClient:
    """Initialize and return the global backend client."""
    async with _client_lock:
        if _client_state.client is not None:
            return _client_state.client

        client = BackendAPIClient(database_url, config=config)
        await client.start()
        _client_state.client = client
        return client


def get_database_pool() -> BackendAPIClient:
    """Return the global backend client."""
    if _client_state.client is not None:
        return _client_state.client

    msg = "Backend client has not been initialized"
    raise BackendClientNotInitializedError(msg)


async def close_database_pool() -> None:
    """Close and clear the global backend client."""
    async with _client_lock:
        if _client_state.client is None:
            return

        await _client_state.client.close()
        _client_state.client = None


def _normalize_api_base_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        msg = "base_url must be set"
        raise BackendConfigurationError(msg)

    if cleaned.endswith("/v1"):
        return cleaned

    return f"{cleaned}/v1"


def _optional_params(**values: Any) -> dict[str, Any] | None:  # noqa: ANN401
    params = {key: value for key, value in values.items() if value is not None}
    if params:
        return params
    return None


def _typed_dict(payload: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    msg = "Expected object payload from backend"
    raise BackendAPIError(msg, status_code=HTTP_STATUS_OK)


def _typed_list(payload: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload

    msg = "Expected list payload from backend"
    raise BackendAPIError(msg, status_code=HTTP_STATUS_OK)


def _to_backend_api_error(response: httpx.Response) -> BackendAPIError:
    payload: dict[str, Any] | None = None
    message = f"Backend API request failed with status {response.status_code}"

    if response.content:
        body = response.json()
        if isinstance(body, dict):
            payload = body
            error_message = body.get("message") or body.get("error")
            if isinstance(error_message, str) and error_message:
                message = error_message

    return BackendAPIError(message, status_code=response.status_code, payload=payload)
