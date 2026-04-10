from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic_settings import BaseSettings, SettingsConfigDict

from capy_discord.database import BackendAPIClient, BackendAPIError, BackendClientConfig, UpdateUserRequest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class _IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_url: str = ""
    test_bot_token: str = ""
    test_user_id: str = ""
    test_deletable_user_id: str = ""
    run_mutation_integration_tests: bool = False


def _load_settings() -> _IntegrationSettings:
    return _IntegrationSettings()


def _bot_integration_client_config(settings: _IntegrationSettings) -> tuple[str, BackendClientConfig]:
    base_url = settings.api_url.strip()
    if not base_url:
        pytest.skip("set API_URL to run backend integration tests manually")
    if "/bot" not in base_url:
        pytest.skip("set API_URL to the bot base route, for example http://localhost:8080/api/v1/bot")

    test_bot_token = settings.test_bot_token.strip()
    if not test_bot_token:
        pytest.skip("set TEST_BOT_TOKEN to run bot-route integration tests")

    return (base_url, BackendClientConfig(bot_token=test_bot_token))


def _require_existing_user_id(settings: _IntegrationSettings) -> str:
    user_id = settings.test_user_id.strip()
    if not user_id:
        pytest.skip("set TEST_USER_ID to run integration tests that require an existing user")
    return user_id


def _require_mutations_enabled(settings: _IntegrationSettings) -> None:
    if not settings.run_mutation_integration_tests:
        pytest.skip("set RUN_MUTATION_INTEGRATION_TESTS=true to run mutating integration tests")


def _assert_optional_string(payload: Mapping[str, object], key: str) -> None:
    value = payload.get(key)
    assert value is None or isinstance(value, str)


def _skip_if_backend_route_unavailable(exc: BackendAPIError, route_name: str) -> None:
    if exc.status_code in {404, 405}:
        pytest.skip(f"{route_name} is not available on the current /bot backend route surface")
    raise exc


async def _safe_delete_event(client: BackendAPIClient, event_id: str) -> None:
    try:
        await client.delete_event(event_id)
    except BackendAPIError as exc:
        if exc.status_code != 404:
            raise


async def _safe_delete_organization(client: BackendAPIClient, organization_id: str) -> None:
    try:
        await client.delete_organization(organization_id)
    except BackendAPIError as exc:
        if exc.status_code != 404:
            raise


async def _safe_unregister_event(client: BackendAPIClient, event_id: str, user_id: str) -> None:
    try:
        await client.unregister_event(event_id, uid=user_id)
    except BackendAPIError as exc:
        if exc.status_code != 404:
            raise


async def _safe_remove_organization_member(
    client: BackendAPIClient,
    organization_id: str,
    user_id: str,
) -> None:
    try:
        await client.remove_organization_member(organization_id, user_id)
    except BackendAPIError as exc:
        if exc.status_code != 404:
            raise


@pytest_asyncio.fixture
async def bot_backend_client() -> AsyncIterator[BackendAPIClient]:
    settings = _load_settings()
    base_url, config = _bot_integration_client_config(settings)
    client = BackendAPIClient(base_url, config=config)
    await client.start()
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def managed_organization(bot_backend_client: BackendAPIClient) -> AsyncIterator[dict[str, Any]]:
    settings = _load_settings()
    _require_mutations_enabled(settings)
    creator_uid = _require_existing_user_id(settings)

    organization = await bot_backend_client.create_organization(
        {
            "name": f"integration-org-{uuid4().hex[:8]}",
            "creator_uid": creator_uid,
        }
    )
    organization_id = str(organization.get("oid", "")).strip()
    if not organization_id:
        pytest.skip("backend did not return an organization id for the created organization")

    try:
        yield organization
    finally:
        await _safe_delete_organization(bot_backend_client, organization_id)


@pytest_asyncio.fixture
async def managed_event(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    organization_id = str(managed_organization.get("oid", "")).strip()
    if not organization_id:
        pytest.skip("managed organization fixture did not produce an oid")

    event = await bot_backend_client.create_event(
        {
            "org_id": organization_id,
            "description": f"integration-event-{uuid4().hex[:8]}",
            "location": "integration-suite",
        }
    )
    event_id = str(event.get("eid", "")).strip()
    if not event_id:
        pytest.skip("backend did not return an event id for the created event")

    try:
        yield event
    finally:
        await _safe_delete_event(bot_backend_client, event_id)


@pytest_asyncio.fixture
async def registered_event_user(
    bot_backend_client: BackendAPIClient,
    managed_event: dict[str, Any],
) -> AsyncIterator[tuple[str, str]]:
    settings = _load_settings()
    user_id = _require_existing_user_id(settings)
    event_id = str(managed_event.get("eid", "")).strip()
    if not event_id:
        pytest.skip("managed event fixture did not produce an eid")

    await bot_backend_client.register_event(event_id, {"uid": user_id, "is_attending": True})

    try:
        yield event_id, user_id
    finally:
        await _safe_unregister_event(bot_backend_client, event_id, user_id)


@pytest_asyncio.fixture
async def organization_member(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
) -> AsyncIterator[tuple[str, str]]:
    settings = _load_settings()
    user_id = _require_existing_user_id(settings)
    organization_id = str(managed_organization.get("oid", "")).strip()
    if not organization_id:
        pytest.skip("managed organization fixture did not produce an oid")

    await bot_backend_client.add_organization_member(organization_id, {"uid": user_id, "is_admin": False})

    try:
        yield organization_id, user_id
    finally:
        await _safe_remove_organization_member(bot_backend_client, organization_id, user_id)


async def test_backend_integration_bot_me(bot_backend_client: BackendAPIClient):
    payload = await bot_backend_client.bot_me()

    _assert_optional_string(payload, "token_id")
    _assert_optional_string(payload, "name")
    _assert_optional_string(payload, "token")
    _assert_optional_string(payload, "created_at")
    _assert_optional_string(payload, "expires_at")
    assert payload.get("is_active") in {None, True, False}


async def test_backend_integration_list_events(bot_backend_client: BackendAPIClient):
    events = await bot_backend_client.list_events(limit=5, offset=0)

    assert isinstance(events, list)
    for event in events:
        assert isinstance(event, dict)
        _assert_optional_string(event, "eid")
        _assert_optional_string(event, "description")
        _assert_optional_string(event, "event_time")
        _assert_optional_string(event, "location")


async def test_backend_integration_create_event(managed_event: dict[str, Any]):
    _assert_optional_string(managed_event, "eid")
    _assert_optional_string(managed_event, "description")
    _assert_optional_string(managed_event, "location")


async def test_backend_integration_get_event(
    bot_backend_client: BackendAPIClient,
    managed_event: dict[str, Any],
):
    event_id = str(managed_event.get("eid", "")).strip()
    event = await bot_backend_client.get_event(event_id)

    assert isinstance(event, dict)
    assert event.get("eid") in {None, event_id}
    _assert_optional_string(event, "description")
    _assert_optional_string(event, "event_time")
    _assert_optional_string(event, "location")


async def test_backend_integration_update_event(
    bot_backend_client: BackendAPIClient,
    managed_event: dict[str, Any],
):
    event_id = str(managed_event.get("eid", "")).strip()
    updated = await bot_backend_client.update_event(
        event_id,
        {
            "description": f"updated-integration-event-{uuid4().hex[:8]}",
            "location": "integration-suite-updated",
        },
    )

    assert updated.get("eid") in {None, event_id}
    assert updated.get("location") in {None, "integration-suite-updated"}


async def test_backend_integration_delete_event(
    bot_backend_client: BackendAPIClient,
    managed_event: dict[str, Any],
):
    event_id = str(managed_event.get("eid", "")).strip()

    await bot_backend_client.delete_event(event_id)

    with pytest.raises(BackendAPIError) as exc_info:
        await bot_backend_client.get_event(event_id)
    assert exc_info.value.status_code == 404


async def test_backend_integration_list_events_by_organization(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
    managed_event: dict[str, Any],
):
    organization_id = str(managed_organization.get("oid", "")).strip()
    created_event_id = str(managed_event.get("eid", "")).strip()

    try:
        events = await bot_backend_client.list_events_by_organization(organization_id, limit=100, offset=0)
    except BackendAPIError as exc:
        _skip_if_backend_route_unavailable(exc, "list_events_by_organization")

    assert isinstance(events, list)
    assert any(isinstance(event, dict) and event.get("eid") == created_event_id for event in events)


async def test_backend_integration_register_event(registered_event_user: tuple[str, str]):
    event_id, user_id = registered_event_user
    assert event_id
    assert user_id


async def test_backend_integration_list_event_registrations(
    bot_backend_client: BackendAPIClient,
    registered_event_user: tuple[str, str],
):
    event_id, user_id = registered_event_user
    registrations = await bot_backend_client.list_event_registrations(event_id)

    assert isinstance(registrations, list)
    assert any(isinstance(registration, dict) and registration.get("uid") == user_id for registration in registrations)


async def test_backend_integration_unregister_event(
    bot_backend_client: BackendAPIClient,
    managed_event: dict[str, Any],
):
    settings = _load_settings()
    _require_mutations_enabled(settings)
    user_id = _require_existing_user_id(settings)
    event_id = str(managed_event.get("eid", "")).strip()

    await bot_backend_client.register_event(event_id, {"uid": user_id, "is_attending": True})
    await bot_backend_client.unregister_event(event_id, uid=user_id)

    registrations = await bot_backend_client.list_event_registrations(event_id)
    assert all(
        not isinstance(registration, dict) or registration.get("uid") != user_id for registration in registrations
    )


async def test_backend_integration_list_organizations(bot_backend_client: BackendAPIClient):
    organizations = await bot_backend_client.list_organizations(limit=5, offset=0)

    assert isinstance(organizations, list)
    for organization in organizations:
        assert isinstance(organization, dict)
        _assert_optional_string(organization, "oid")
        _assert_optional_string(organization, "name")


async def test_backend_integration_create_organization(managed_organization: dict[str, Any]):
    _assert_optional_string(managed_organization, "oid")
    _assert_optional_string(managed_organization, "name")


async def test_backend_integration_get_organization(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
):
    organization_id = str(managed_organization.get("oid", "")).strip()
    organization = await bot_backend_client.get_organization(organization_id)

    assert isinstance(organization, dict)
    assert organization.get("oid") in {None, organization_id}
    _assert_optional_string(organization, "name")


async def test_backend_integration_update_organization(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
):
    organization_id = str(managed_organization.get("oid", "")).strip()
    updated = await bot_backend_client.update_organization(
        organization_id,
        {"name": f"updated-integration-org-{uuid4().hex[:8]}"},
    )

    assert updated.get("oid") in {None, organization_id}


async def test_backend_integration_delete_organization(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
):
    organization_id = str(managed_organization.get("oid", "")).strip()

    await bot_backend_client.delete_organization(organization_id)

    with pytest.raises(BackendAPIError) as exc_info:
        await bot_backend_client.get_organization(organization_id)
    assert exc_info.value.status_code == 404


async def test_backend_integration_list_organization_events(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
    managed_event: dict[str, Any],
):
    organization_id = str(managed_organization.get("oid", "")).strip()
    created_event_id = str(managed_event.get("eid", "")).strip()

    try:
        events = await bot_backend_client.list_organization_events(organization_id, limit=100, offset=0)
    except BackendAPIError as exc:
        _skip_if_backend_route_unavailable(exc, "list_organization_events")

    assert isinstance(events, list)
    assert any(isinstance(event, dict) and event.get("eid") == created_event_id for event in events)


async def test_backend_integration_add_organization_member(organization_member: tuple[str, str]):
    organization_id, user_id = organization_member
    assert organization_id
    assert user_id


async def test_backend_integration_list_organization_members(
    bot_backend_client: BackendAPIClient,
    organization_member: tuple[str, str],
):
    organization_id, user_id = organization_member
    members = await bot_backend_client.list_organization_members(organization_id)

    assert isinstance(members, list)
    assert any(isinstance(member, dict) and member.get("uid") == user_id for member in members)


async def test_backend_integration_remove_organization_member(
    bot_backend_client: BackendAPIClient,
    managed_organization: dict[str, Any],
):
    settings = _load_settings()
    _require_mutations_enabled(settings)
    user_id = _require_existing_user_id(settings)
    organization_id = str(managed_organization.get("oid", "")).strip()

    await bot_backend_client.add_organization_member(organization_id, {"uid": user_id, "is_admin": False})
    await bot_backend_client.remove_organization_member(organization_id, user_id)

    members = await bot_backend_client.list_organization_members(organization_id)
    assert all(not isinstance(member, dict) or member.get("uid") != user_id for member in members)


async def test_backend_integration_get_user(bot_backend_client: BackendAPIClient):
    settings = _load_settings()
    user_id = _require_existing_user_id(settings)

    user = await bot_backend_client.get_user(user_id)

    assert isinstance(user, dict)
    _assert_optional_string(user, "uid")
    _assert_optional_string(user, "first_name")
    _assert_optional_string(user, "last_name")


async def test_backend_integration_update_user(bot_backend_client: BackendAPIClient):
    settings = _load_settings()
    _require_mutations_enabled(settings)
    user_id = _require_existing_user_id(settings)

    current_user = await bot_backend_client.get_user(user_id)
    update_payload: UpdateUserRequest = {}
    if isinstance(current_user.get("first_name"), str):
        update_payload["first_name"] = current_user["first_name"]
    if isinstance(current_user.get("last_name"), str):
        update_payload["last_name"] = current_user["last_name"]
    if not update_payload:
        pytest.skip("backend user payload did not include fields safe to round-trip for update_user")

    try:
        updated_user = await bot_backend_client.update_user(user_id, update_payload)
    except BackendAPIError as exc:
        _skip_if_backend_route_unavailable(exc, "update_user")

    assert isinstance(updated_user, dict)
    assert updated_user.get("uid") in {None, user_id}


async def test_backend_integration_delete_user(bot_backend_client: BackendAPIClient):
    settings = _load_settings()
    _require_mutations_enabled(settings)
    deletable_user_id = settings.test_deletable_user_id.strip()
    if not deletable_user_id:
        pytest.skip("set TEST_DELETABLE_USER_ID to run delete_user integration test")

    try:
        await bot_backend_client.delete_user(deletable_user_id)
    except BackendAPIError as exc:
        _skip_if_backend_route_unavailable(exc, "delete_user")


async def test_backend_integration_list_user_events(bot_backend_client: BackendAPIClient):
    settings = _load_settings()
    user_id = _require_existing_user_id(settings)

    events = await bot_backend_client.list_user_events(user_id)

    assert isinstance(events, list)
    for event in events:
        assert isinstance(event, dict)
        _assert_optional_string(event, "eid")
        _assert_optional_string(event, "description")


async def test_backend_integration_list_user_organizations(bot_backend_client: BackendAPIClient):
    settings = _load_settings()
    user_id = _require_existing_user_id(settings)

    organizations = await bot_backend_client.list_user_organizations(user_id)

    assert isinstance(organizations, list)
    for organization in organizations:
        assert isinstance(organization, dict)
        _assert_optional_string(organization, "oid")
        _assert_optional_string(organization, "name")
