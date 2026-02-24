# Phase 3 Tech Spec: Telemetry API Export

## Context

Phases 1-2b are complete. The bot captures every Discord interaction, queues events via `asyncio.Queue`, processes them every second into in-memory metrics (`TelemetryMetrics`), and writes structured debug logs. All data stays in-process and resets on bot restart.

Phase 3 adds a **batched HTTP export layer**: events are buffered in a secondary list and periodically POSTed to the CAPY core API gateway (`https://api.capyrpi.org/v1/telemetry`), which persists them to PostgreSQL. The bot owns transport only — no direct DB connection.

---

## Architecture Overview

```
Discord Event
      │
      ▼
on_interaction / on_app_command_completion / log_command_failure
      │
      ▼
asyncio.Queue (existing, maxsize=1000)
      │
      ▼ every 1s (_consumer_task — existing)
_dispatch_event()
   ├── _log_interaction / _log_completion       (existing — file log)
   ├── _record_*_metrics()                      (existing — in-memory)
   └── _api_buffer.append(event.data)           ← NEW
      │
      ▼ every 30s (_flush_task — NEW)
_flush_to_api()
      │
      ▼
TelemetryApiClient.post_telemetry_batch()      ← NEW (_api_client.py)
   ├── _build_payload() → TelemetryBatchPayload (Pydantic)
   ├── OAuth client credentials token (Authentik)
   └── POST https://api.capyrpi.org/v1/telemetry
      │
      ▼
API Gateway → PostgreSQL
```

---

## API Schema Design

### `POST /v1/telemetry` — Request Body

Mixed batch: both `interaction` and `completion` events in one `events` array.
`event_type` is the discriminator. The API links them via `correlation_id` at query time.

```json
{
  "bot_version": "0.1.0",
  "sent_at": "2026-02-20T14:32:01.123456Z",
  "events": [
    {
      "event_type": "interaction",
      "correlation_id": "a3f9c1d20b4e",
      "timestamp": "2026-02-20T14:31:58.442000Z",
      "interaction_type": "slash_command",
      "user_id": 123456789012345678,
      "username": "alice#0001",
      "command_name": "ping",
      "guild_id": 987654321098765432,
      "guild_name": "CAPY Server",
      "channel_id": 111222333444555666,
      "options": {"arg1": "value"}
    },
    {
      "event_type": "completion",
      "correlation_id": "a3f9c1d20b4e",
      "timestamp": "2026-02-20T14:31:58.551000Z",
      "command_name": "ping",
      "status": "success",
      "duration_ms": 109.3,
      "error_type": null
    }
  ]
}
```

**Field notes:**
- `sent_at` — envelope timestamp for measuring pipeline lag.
- `bot_version` — correlates incidents to deployments.
- `user_id`, `guild_id`, `channel_id` — 64-bit Discord snowflakes stored as `bigint` in Postgres.
- `guild_id` / `guild_name` — nullable (DM interactions have no guild).
- `options` — stored as JSONB on the API side.
- `error_type` — only present on completion events with non-success status.
- `interaction_type` values: `slash_command`, `button`, `dropdown`, `modal`, `autocomplete`.
- `status` values: `success`, `user_error`, `internal_error`.

### Response

**202 Accepted:**
```json
{"accepted": 12, "batch_id": "uuid-string"}
```

**400 Bad Request:**
```json
{"error": "validation_error", "detail": "events[2].event_type must be 'interaction' or 'completion'"}
```

**401 Unauthorized:**
```json
{"error": "unauthorized"}
```

The bot only inspects the HTTP status code. Non-2xx → log warning + drop batch.

---

### `GET /v1/telemetry/events` — Paginated Event List

Returns raw events from the database with filtering and pagination. Used by future tooling and the Phase 4 dashboard.

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `event_type` | `interaction` \| `completion` | Filter to one event type |
| `command_name` | string | Filter by command name |
| `guild_id` | integer | Filter to a specific guild |
| `user_id` | integer | Filter to a specific user |
| `status` | `success` \| `user_error` \| `internal_error` | Filter completions by status |
| `from` | ISO 8601 UTC | Start of time range (inclusive) |
| `to` | ISO 8601 UTC | End of time range (inclusive) |
| `limit` | integer | Results per page. Default: `50`, max: `500` |
| `offset` | integer | Pagination offset. Default: `0` |

**Response (200 OK):**
```json
{
  "total": 1250,
  "limit": 50,
  "offset": 0,
  "events": [
    {
      "event_type": "interaction",
      "correlation_id": "a3f9c1d20b4e",
      "timestamp": "2026-02-20T14:31:58.442000Z",
      "received_at": "2026-02-20T14:32:01.100000Z",
      "interaction_type": "slash_command",
      "user_id": 123456789012345678,
      "username": "alice#0001",
      "command_name": "ping",
      "guild_id": 987654321098765432,
      "guild_name": "CAPY Server",
      "channel_id": 111222333444555666,
      "options": {},
      "bot_version": "0.1.0"
    },
    {
      "event_type": "completion",
      "correlation_id": "a3f9c1d20b4e",
      "timestamp": "2026-02-20T14:31:58.551000Z",
      "received_at": "2026-02-20T14:32:01.100000Z",
      "command_name": "ping",
      "status": "success",
      "duration_ms": 109.3,
      "error_type": null,
      "bot_version": "0.1.0"
    }
  ]
}
```

`received_at` is the server-side ingestion timestamp (set by the API). The difference between `timestamp` and `received_at` is the pipeline lag.

---

### `GET /v1/telemetry/metrics` — Aggregate Statistics

Returns pre-aggregated metrics computed from the database over an optional time window. Designed for the future `/stats` Discord command and the Phase 4 dashboard.

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `from` | ISO 8601 UTC | Start of time range. Default: 30 days ago |
| `to` | ISO 8601 UTC | End of time range. Default: now |
| `guild_id` | integer | Scope metrics to a specific guild |

**Response (200 OK):**
```json
{
  "period": {
    "from": "2026-01-01T00:00:00Z",
    "to": "2026-01-31T23:59:59Z"
  },
  "totals": {
    "interactions": 4821,
    "unique_users": 142,
    "guilds_active": 3
  },
  "by_type": {
    "slash_command": 3201,
    "button": 1100,
    "modal": 420,
    "dropdown": 100
  },
  "top_commands": [
    {"command": "ping",    "invocations": 850, "success_rate": 0.99, "avg_latency_ms": 112.3},
    {"command": "profile", "invocations": 720, "success_rate": 0.97, "avg_latency_ms": 234.1},
    {"command": "help",    "invocations": 510, "success_rate": 1.0,  "avg_latency_ms":  88.4}
  ],
  "completions": {
    "success": 3150,
    "user_error": 42,
    "internal_error": 9
  },
  "top_errors": [
    {"error_type": "UserFriendlyError", "count": 38},
    {"error_type": "RuntimeError",      "count":  9}
  ]
}
```

`top_commands` is computed via a JOIN between `telemetry_interactions` and `telemetry_completions` on `correlation_id`, grouped by `command_name`, ordered by `invocations DESC`, limited to 10.

`success_rate` = `success_count / total_completions` for that command. `avg_latency_ms` excludes failed completions.

---

## OAuth Client Credentials Flow

Service-to-service auth using Authentik's OAuth 2.0 client credentials grant.

**Flow:**
1. Bot POSTs `grant_type=client_credentials` + credentials to the Authentik token endpoint.
2. Authentik returns `{"access_token": "...", "expires_in": 3600, "token_type": "Bearer"}`.
3. Bot caches token; attaches `Authorization: Bearer <token>` to every telemetry request.
4. On 401: discard cached token, re-fetch, retry once. Log + drop on second failure.
5. Token pre-emptively refreshed when < 60 seconds remain (`expires_in - 30s` buffer).

**No-auth mode:** If `TELEMETRY_OAUTH_URL` is empty, skip token fetch. Useful for local dev if the API accepts unauthenticated requests.

**Disabled mode:** If `TELEMETRY_ENABLED=false` (the default), `post_telemetry_batch` is a no-op returning `True`. No HTTP calls are made. The buffer still accumulates locally but is never flushed. This is the primary safety guard — prevents accidental calls in environments without credentials.

> **Action required:** The API team needs to provision an Authentik service account for the bot and provide `TELEMETRY_OAUTH_URL`, `TELEMETRY_CLIENT_ID`, and `TELEMETRY_CLIENT_SECRET`. The implementation can proceed before credentials are issued since `TELEMETRY_ENABLED=false` is the default.

---

## New Files

### `capy_discord/exts/core/_api_client.py`

HTTP client with OAuth token management. Underscore prefix prevents the extension loader from treating it as a cog.

**Classes and functions:**
```python
@dataclass
class _OAuthToken:
    access_token: str
    expires_at: datetime   # UTC; now + expires_in - 30s

class _TokenFetchError(Exception): ...   # raised by _fetch_token on non-2xx

def _build_payload(events: list[dict[str, Any]], bot_version: str) -> dict[str, Any]:
    # Validates each event via Pydantic, wraps in TelemetryBatchPayload,
    # returns model_dump(mode="json") — fully JSON-serializable dict

class TelemetryApiClient:
    def __init__(self, settings: Settings) -> None
    async def start(self) -> None          # creates httpx.AsyncClient (not in __init__)
    async def close(self) -> None          # awaits _http.aclose()
    async def post_telemetry_batch(self, events: list[dict[str, Any]]) -> bool
    async def _get_valid_token(self) -> str
    async def _fetch_token(self) -> str    # POSTs to token endpoint; raises _TokenFetchError
    async def _build_headers(self) -> dict[str, str]
```

**httpx timeout (constants, not config):**
```python
httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
```

**`post_telemetry_batch` logic:**
1. Return `True` early if `telemetry_enabled=False` or empty batch.
2. Build payload via `_build_payload`.
3. Build headers via `_build_headers` (fetches/caches OAuth token if configured).
4. POST to `telemetry_api_url`.
5. On 401: `self._token = None` → rebuild headers → retry once.
6. On `response.is_success`: debug log, return `True`.
7. On non-2xx or any exception: log warning/exception, return `False`. Never re-raise.

**`bot_version`:** Retrieved in `start()` via `importlib.metadata.version("capy-discord")`. Defaults to `"unknown"` on `PackageNotFoundError`.

---

### `capy_discord/exts/core/_schemas.py`

Pydantic `BaseModel` classes for API payload serialization.

```python
class InteractionEventPayload(BaseModel):
    event_type: Literal["interaction"]
    correlation_id: str
    timestamp: datetime
    interaction_type: str
    user_id: int
    username: str
    command_name: str | None
    guild_id: int | None
    guild_name: str | None
    channel_id: int
    options: dict[str, Any] = Field(default_factory=dict)

class CompletionEventPayload(BaseModel):
    event_type: Literal["completion"]
    correlation_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    command_name: str
    status: Literal["success", "user_error", "internal_error"]
    duration_ms: float
    error_type: str | None = None

class TelemetryBatchPayload(BaseModel):
    bot_version: str
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: list[InteractionEventPayload | CompletionEventPayload]
```

`model_dump(mode="json")` handles `datetime` → ISO 8601 string serialization automatically.

`CompletionEventPayload.timestamp` defaults to `datetime.now(UTC)` because existing completion events don't carry a wall-clock timestamp (only `duration_ms`).

---

### `tests/capy_discord/exts/core/__init__.py`

Empty. Creates the package directory for the new test file. This directory does not currently exist.

---

### `tests/capy_discord/exts/core/test_api_client.py`

See Test Strategy section below.

---

## Modified Files

### `pyproject.toml`

Add to `[project].dependencies`:
```toml
"httpx>=0.28.0",
```

No additional test dependency needed. `unittest.mock.AsyncMock` patches `httpx.AsyncClient` methods directly.

---

### `capy_discord/config.py`

Add to `Settings` after existing fields:
```python
# Telemetry API Export (Phase 3)
telemetry_enabled: bool = False
telemetry_api_url: str = "https://api.capyrpi.org/v1/telemetry"
telemetry_oauth_url: str = ""
telemetry_client_id: str = ""
telemetry_client_secret: str = ""  # noqa: S105
telemetry_batch_size: int = 100
telemetry_flush_interval: int = 30
```

**Env vars (pydantic-settings flat field mapping):**

| Field | Env var | Default |
|---|---|---|
| `telemetry_enabled` | `TELEMETRY_ENABLED` | `false` |
| `telemetry_api_url` | `TELEMETRY_API_URL` | `https://api.capyrpi.org/v1/telemetry` |
| `telemetry_oauth_url` | `TELEMETRY_OAUTH_URL` | `""` |
| `telemetry_client_id` | `TELEMETRY_CLIENT_ID` | `""` |
| `telemetry_client_secret` | `TELEMETRY_CLIENT_SECRET` | `""` |
| `telemetry_batch_size` | `TELEMETRY_BATCH_SIZE` | `100` |
| `telemetry_flush_interval` | `TELEMETRY_FLUSH_INTERVAL` | `30` |

`# noqa: S105` on `telemetry_client_secret` — Ruff's `S105` flags the field name as a potential hardcoded secret, but the empty string is explicitly not a secret.

---

### `capy_discord/exts/core/telemetry.py`

**New imports:**
```python
from capy_discord.config import settings as _settings
from capy_discord.exts.core._api_client import TelemetryApiClient
```

**New module constant (evaluated once at import; drives `tasks.loop`):**
```python
_FLUSH_INTERVAL_SECONDS: int = _settings.telemetry_flush_interval
```

**`__init__` additions:**
```python
self._api_buffer: list[dict[str, Any]] = []
self._api_client = TelemetryApiClient(_settings)
```

`_api_buffer` is a plain list — only ever accessed from the event loop sequentially, no concurrency concern.

**Updated `cog_load`:**
```python
async def cog_load(self) -> None:
    await self._api_client.start()
    self._consumer_task.start()
    self._flush_task.start()
```

**Updated `cog_unload`:**
```python
async def cog_unload(self) -> None:
    self._flush_task.cancel()
    self._consumer_task.cancel()
    self._drain_queue()         # processes remaining queue events into _api_buffer
    await self._flush_to_api()  # best-effort final flush
    await self._api_client.close()
```

Ordering is critical: cancel tasks first → drain queue (populates buffer) → flush → close client.

**New `_flush_task`:**
```python
@tasks.loop(seconds=_FLUSH_INTERVAL_SECONDS)
async def _flush_task(self) -> None:
    await self._flush_to_api()

@_flush_task.before_loop
async def _before_flush(self) -> None:
    await self.bot.wait_until_ready()
```

**New `_flush_to_api`:**
```python
async def _flush_to_api(self) -> None:
    """Flush up to batch_size buffered events to the telemetry API.

    Snapshots and clears the buffer before the HTTP call so new events
    continue accumulating while the request is in flight.

    On failure, events are logged-and-dropped (not re-queued). On shutdown,
    only one batch is flushed; events beyond batch_size are dropped.
    """
    if not self._api_buffer:
        return
    batch = self._api_buffer[:_settings.telemetry_batch_size]
    del self._api_buffer[:_settings.telemetry_batch_size]
    self.log.debug("Flushing %d telemetry events to API", len(batch))
    await self._api_client.post_telemetry_batch(batch)
```

**Modified `_dispatch_event`** — append to `_api_buffer` after existing processing:
```python
if event.event_type == "interaction":
    self._log_interaction(event.data)
    self._record_interaction_metrics(event.data)
    self._api_buffer.append(event.data)          # NEW
elif event.event_type == "completion":
    self._log_completion(**event.data)
    self._record_completion_metrics(event.data)
    self._api_buffer.append(event.data)          # NEW
else:
    self.log.warning(...)                        # unchanged; unknown types skip buffer
```

**Update module docstring** (change "Phase 2b" header to "Phase 3") and `cog_load` info log:
```python
self.log.info(
    "Telemetry cog initialized - Phase 3: API export (enabled=%s)",
    _settings.telemetry_enabled,
)
```

---

### `tests/capy_discord/exts/test_telemetry.py`

Add a second fixture for flush-related tests (keeps existing `cog` fixture untouched):

```python
@pytest.fixture
def cog_with_mock_client(bot):
    with patch.object(Telemetry, "cog_load", return_value=None):
        c = Telemetry(bot)
    c.log = MagicMock()
    c._api_client = MagicMock()
    c._api_client.post_telemetry_batch = AsyncMock(return_value=True)
    return c
```

**New tests (8 functions):**

| Test | What it verifies |
|---|---|
| `test_dispatch_event_populates_api_buffer` | Interaction event appended to `_api_buffer` |
| `test_dispatch_completion_populates_api_buffer` | Completion event appended to `_api_buffer` |
| `test_dispatch_unknown_type_does_not_populate_buffer` | `event_type="bogus"` skips buffer |
| `test_flush_to_api_clears_buffer` | 3 events in → 0 remaining after flush |
| `test_flush_to_api_empty_buffer_no_http_call` | Empty buffer → `post_telemetry_batch` never called |
| `test_flush_to_api_respects_batch_size` | `batch_size + 10` events → 10 remain after flush |
| `test_flush_to_api_drops_on_api_failure` | `post_telemetry_batch` returns `False` → buffer still cleared |
| `test_cog_unload_flushes_remaining_buffer` | `_drain_queue()` + `_flush_to_api()` sequence calls `post_telemetry_batch` |

---

## Test Strategy: `tests/capy_discord/exts/core/test_api_client.py`

Mock strategy: after `await client.start()` creates the real `httpx.AsyncClient`, override `client._http.post` with `AsyncMock`.

**Token management (7 tests):**
- `test_fetch_token_success` — POST returns `{"access_token": "tok", "expires_in": 3600}`, assert token cached
- `test_fetch_token_failure_raises` — POST returns 500, assert `_TokenFetchError` raised
- `test_get_valid_token_uses_cache` — valid unexpired token in cache, assert no second HTTP call
- `test_get_valid_token_refreshes_expired` — `expires_at` in the past, assert `_fetch_token` called
- `test_build_headers_with_oauth` — assert `{"Authorization": "Bearer tok"}` returned
- `test_build_headers_without_oauth_url` — `telemetry_oauth_url=""`, assert `{}` returned
- `test_build_headers_token_failure_returns_empty` — `_TokenFetchError` in `_get_valid_token`, assert `{}` returned and no exception propagates

**`post_telemetry_batch` (8 tests):**
- `test_post_batch_success` — 202 → `True`, debug logged
- `test_post_batch_disabled_returns_true` — `telemetry_enabled=False` → `True`, no HTTP call
- `test_post_batch_empty_returns_true` — `[]` → `True`, no HTTP call
- `test_post_batch_401_retries_once` — first 401, second 202 → `True`, POST called exactly twice
- `test_post_batch_401_retry_also_fails` — both 401 → `False`, warning logged
- `test_post_batch_non_2xx_drops` — 500 → `False`, warning logged
- `test_post_batch_network_error_drops` — `httpx.ConnectError` → `False`, exception logged, does not re-raise
- `test_post_batch_timeout_drops` — `httpx.TimeoutException` → `False`

---

## End-to-End Flow (user runs `/ping`)

1. `on_interaction` fires → 12-char `correlation_id` generated → `TelemetryEvent("interaction", data)` put on `asyncio.Queue`
2. `Ping` cog handles the command independently, sends pong embed
3. `on_app_command_completion` fires → `duration_ms` computed → `TelemetryEvent("completion", data)` enqueued
4. **1 second later** — `_consumer_task` drains queue → `_dispatch_event` runs for both events:
   - Writes to telemetry log file (existing)
   - Updates in-memory `TelemetryMetrics` counters (existing)
   - Appends both event dicts to `_api_buffer` (new)
5. **At 30-second mark** — `_flush_task` fires → `_flush_to_api()`:
   - Snapshots up to 100 events from `_api_buffer`, clears them immediately
   - Calls `await self._api_client.post_telemetry_batch(batch)`
   - `_build_payload` validates each event via Pydantic, wraps in `TelemetryBatchPayload`, calls `model_dump(mode="json")`
   - `_build_headers` fetches OAuth token from Authentik (or returns cached token)
   - `httpx.AsyncClient.post("https://api.capyrpi.org/v1/telemetry", json=payload, headers=headers)`
   - API gateway validates JWT, inserts rows into PostgreSQL, returns `202 {"accepted": 2}`
   - Debug log: `"Telemetry batch of 2 events accepted"`
6. Next 30-second cycle starts fresh

**On 401:** `_token = None` → re-fetch from Authentik → retry once → log + drop on second failure.
**On network failure:** `except Exception` → log exception → return `False` → buffer cleared → bot continues unaffected.
**On shutdown:** Cancel tasks → drain remaining queue events into buffer → final flush (up to `batch_size` events) → close `httpx.AsyncClient`.

---

## PostgreSQL Database Schema

The API gateway owns all DDL. The bot never touches the database directly.

### `telemetry_interactions`

Stores one row per interaction event (slash command invoked, button clicked, modal submitted, etc.).

```sql
CREATE TABLE telemetry_interactions (
    id               BIGSERIAL     PRIMARY KEY,
    correlation_id   CHAR(12)      NOT NULL,
    timestamp        TIMESTAMPTZ   NOT NULL,
    received_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    interaction_type VARCHAR(20)   NOT NULL,
    user_id          BIGINT        NOT NULL,
    username         VARCHAR(100)  NOT NULL,
    command_name     VARCHAR(100),
    guild_id         BIGINT,
    guild_name       VARCHAR(100),
    channel_id       BIGINT        NOT NULL,
    options          JSONB         NOT NULL DEFAULT '{}',
    bot_version      VARCHAR(20)   NOT NULL DEFAULT 'unknown'
);
```

**Column notes:**
- `correlation_id CHAR(12)` — fixed-length hex string from `uuid.uuid4().hex[:12]`. Links to `telemetry_completions.correlation_id`.
- `timestamp` — when the interaction occurred on Discord (from `interaction.created_at`, UTC).
- `received_at` — when the API ingested the event. The delta `received_at - timestamp` = pipeline lag.
- `interaction_type` — one of: `slash_command`, `button`, `dropdown`, `modal`, `autocomplete`.
- `guild_id` / `guild_name` — nullable; `NULL` for DM interactions.
- `command_name` — nullable; `NULL` for non-command interactions (e.g. button clicks without a named command).
- `options JSONB` — slash command arguments, modal field values, or select menu values. Stored as JSONB for flexibility.
- `bot_version` — bot deployment version at time of event. Useful for correlating regressions to releases.

---

### `telemetry_completions`

Stores one row per command outcome (success or failure). Linked to `telemetry_interactions` via `correlation_id`.

```sql
CREATE TABLE telemetry_completions (
    id             BIGSERIAL     PRIMARY KEY,
    correlation_id CHAR(12)      NOT NULL,
    timestamp      TIMESTAMPTZ   NOT NULL,
    received_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    command_name   VARCHAR(100)  NOT NULL,
    status         VARCHAR(20)   NOT NULL,
    duration_ms    NUMERIC(10,2),
    error_type     VARCHAR(100),
    bot_version    VARCHAR(20)   NOT NULL DEFAULT 'unknown',

    CONSTRAINT chk_completion_status
        CHECK (status IN ('success', 'user_error', 'internal_error'))
);
```

**Column notes:**
- No `FOREIGN KEY` constraint to `telemetry_interactions` — correlation is soft (JOIN at query time). This avoids referential integrity failures if a completion arrives before its interaction in edge cases.
- `duration_ms NUMERIC(10,2)` — nullable as a safety measure; should always be present from the bot but the API should not reject a batch over a missing value.
- `error_type` — Python exception class name (e.g. `RuntimeError`, `UserFriendlyError`). NULL on `status = 'success'`.
- `timestamp` — set to `datetime.now(UTC)` on the bot side at completion time (not interaction start time). See `CompletionEventPayload`.

---

### Indexes

```sql
-- telemetry_interactions
CREATE INDEX idx_interactions_timestamp
    ON telemetry_interactions (timestamp);

CREATE INDEX idx_interactions_correlation_id
    ON telemetry_interactions (correlation_id);

CREATE INDEX idx_interactions_guild_id
    ON telemetry_interactions (guild_id, timestamp)
    WHERE guild_id IS NOT NULL;

CREATE INDEX idx_interactions_command_name
    ON telemetry_interactions (command_name, timestamp)
    WHERE command_name IS NOT NULL;

CREATE INDEX idx_interactions_user_id
    ON telemetry_interactions (user_id);

CREATE INDEX idx_interactions_type
    ON telemetry_interactions (interaction_type, timestamp);

-- telemetry_completions
CREATE INDEX idx_completions_timestamp
    ON telemetry_completions (timestamp);

CREATE INDEX idx_completions_correlation_id
    ON telemetry_completions (correlation_id);

CREATE INDEX idx_completions_command_status
    ON telemetry_completions (command_name, status);

CREATE INDEX idx_completions_status_time
    ON telemetry_completions (status, timestamp);

CREATE INDEX idx_completions_error_type
    ON telemetry_completions (error_type)
    WHERE error_type IS NOT NULL;
```

**Rationale:**
- Time-range queries on `timestamp` are the most common access pattern for both the metrics endpoint and the events list endpoint.
- `correlation_id` indexes enable efficient JOIN between the two tables for `top_commands` aggregation.
- Partial indexes (`WHERE guild_id IS NOT NULL`, `WHERE error_type IS NOT NULL`) avoid indexing null rows, keeping index size smaller.
- `idx_interactions_user_id` supports per-user filtering and `COUNT(DISTINCT user_id)` in metrics.

**Not included in Phase 3:**
- GIN index on `options JSONB` — not needed until queries inside `options` are required (Phase 4).
- Table partitioning by `timestamp` — worth adding once row counts exceed ~10M. Defer to Phase 4.
- `pg_cron` data retention job — suggested policy is 90 days, but the implementation is left to the API team.

---

### Key Query Examples

**Top commands (used by `GET /v1/telemetry/metrics`):**
```sql
SELECT
    i.command_name,
    COUNT(i.id)                                                          AS invocations,
    AVG(c.duration_ms)                                                   AS avg_latency_ms,
    SUM(CASE WHEN c.status = 'success' THEN 1 ELSE 0 END)::float
        / NULLIF(COUNT(c.id), 0)                                        AS success_rate
FROM telemetry_interactions i
LEFT JOIN telemetry_completions c ON i.correlation_id = c.correlation_id
WHERE i.timestamp BETWEEN :from AND :to
  AND i.command_name IS NOT NULL
GROUP BY i.command_name
ORDER BY invocations DESC
LIMIT 10;
```

**Unique users over a time window:**
```sql
SELECT COUNT(DISTINCT user_id)
FROM telemetry_interactions
WHERE timestamp BETWEEN :from AND :to;
```

**Error breakdown:**
```sql
SELECT error_type, COUNT(*) AS count
FROM telemetry_completions
WHERE timestamp BETWEEN :from AND :to
  AND error_type IS NOT NULL
GROUP BY error_type
ORDER BY count DESC;
```

---

## Verification Plan

1. **Unit tests:** `uv run task test` — all 46 existing tests + ~22 new tests pass, 0 warnings
2. **Lint:** `uv run task lint` — no Ruff violations (verify `# noqa: S105` on `telemetry_client_secret`)
3. **Disabled mode (default):** Start bot with no `TELEMETRY_*` env vars set → confirm no HTTP calls and no errors in logs
4. **Integration smoke test:** Set `TELEMETRY_ENABLED=true` + real credentials, run bot, trigger `/ping`, check API gateway logs for 202 and confirm PostgreSQL row insertion
5. **Shutdown flush:** Stop bot while events are buffered, confirm `"Flushing N telemetry events to API"` appears in logs before shutdown completes
