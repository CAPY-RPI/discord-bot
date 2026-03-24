# Phase 3 — Telemetry API & Database

## Phase Context

| Phase | Status | What it did |
|-------|--------|-------------|
| 2a | Complete | Async queue buffering — events enqueued in-process, consumed by background task |
| 2b | Complete | In-memory analytics — `TelemetryMetrics` counters, latency stats, `get_metrics()` accessor |
| **3** | **Planned** | Persist events to PostgreSQL via an external API gateway |
| 4 | Future | Web dashboard consuming the Phase 3 data |

This document covers Phase 3. The bot code already captures and queues all events correctly — Phase 3 wires the queue consumer to POST batches to the API instead of (or in addition to) logging them.

---

## System Overview

```
Discord event
     │
     ▼
on_interaction / on_app_command_completion / log_command_failure
     │  (non-blocking, never raises)
     ▼
asyncio.Queue (max 1000 events, drop on full)
     │
     ▼  (background task, every 1.0s)
POST /api/v1/telemetry/batch  ──►  API Gateway  ──►  PostgreSQL
                                                    ├── telemetry_interactions
                                                    └── telemetry_completions
```

The bot never connects to the database directly. The API gateway owns the database, validates payloads, and writes rows. The bot only POSTs batches.

The API gateway and dashboard backend are the **same FastAPI service** (port 8000). All routes — write and read — share the `/api/v1` prefix. The bot's `TELEMETRY_API_URL` env var must point to this service.

---

## Bot-Side Behavior

These constants in `telemetry.py` govern how events flow through the bot:

| Constant | Value | Meaning |
|----------|-------|---------|
| `_QUEUE_MAX_SIZE` | `1000` | Hard cap on the in-memory queue. Events are **dropped** (not buffered elsewhere) if the queue is full. |
| `_CONSUMER_INTERVAL_SECONDS` | `1.0` | Background task drains the queue every second. |
| `_STALE_THRESHOLD_SECONDS` | `60` | Pending entries older than 60s with no completion are deleted to prevent memory leaks. This happens on every `on_interaction` call. |

### Event capture

Three entry points populate the queue:

| Entry point | Fires when | Produces |
|------------|-----------|---------|
| `on_interaction` | Every user interaction with the bot | `interaction` event |
| `on_app_command_completion` | Slash command resolves successfully | `completion` event (`status: success`) |
| `log_command_failure` | Called from `bot.py`'s `on_tree_error` | `completion` event (`status: user_error` or `internal_error`) |

**Buttons and modals** produce an `interaction` event but never a `completion` — `on_app_command_completion` only fires for slash commands.

**Autocomplete** interactions (`interaction_type: autocomplete`) fire on every keystroke while a user types a slash command argument. These are currently captured but should be filtered out before Phase 3 — they are high-frequency noise with no analytical value.

### Correlation ID

On every `on_interaction`, the bot generates a 12-character hex ID:

```python
correlation_id = uuid.uuid4().hex[:12]  # e.g. "a3f9c1d20b4e"
```

It stores `(correlation_id, start_time_monotonic)` in `_pending[interaction.id]`. When the completion fires, the bot pops the entry, computes `duration_ms`, and includes the same `correlation_id` in the completion event. This is the only link between the two rows in the database — there is intentionally no FK constraint.

If a completion fires for an interaction that has no pending entry (missed event, race condition, or stale cleanup), the bot falls back to `correlation_id = "unknown"` and `duration_ms` measured from that moment — effectively 0ms.

---

## Schema

Two append-only tables. The API gateway INSERTs into both; nothing is ever updated or deleted.

### `telemetry_interactions`

One row per Discord interaction (slash command, button click, modal submit, dropdown).

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | `BIGSERIAL` | NO | Auto-incrementing surrogate PK — set by DB, never in payload |
| `correlation_id` | `VARCHAR(12)` | NO | 12-char hex; links to completions via soft join |
| `timestamp` | `TIMESTAMPTZ` | NO | When the interaction occurred (UTC) — from bot payload |
| `received_at` | `TIMESTAMPTZ` | NO | When the API ingested it — set by API as `NOW()`, never in payload |
| `interaction_type` | `VARCHAR(20)` | NO | See interaction type reference below |
| `user_id` | `BIGINT` | NO | Discord snowflake — stable, immutable identifier |
| `command_name` | `VARCHAR(100)` | YES | NULL for buttons and modals (see Phase 3 work items) |
| `guild_id` | `BIGINT` | YES | NULL in DMs |
| `guild_name` | `VARCHAR(100)` | YES | Guild name at time of event; NULL in DMs |
| `channel_id` | `BIGINT` | NO | Discord snowflake |
| `options` | `JSONB` | NO | Command args, modal field values, button custom_id, etc. Defaults to `{}` |
| `bot_version` | `VARCHAR(20)` | NO | Bot version at time of event; defaults to `'unknown'` (see Phase 3 work items) |

### `telemetry_completions`

One row per command outcome. Slash commands only — buttons and modals do not produce completion rows.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | `BIGSERIAL` | NO | Auto-incrementing surrogate PK — set by DB, never in payload |
| `correlation_id` | `VARCHAR(12)` | NO | Links to `telemetry_interactions` via soft join |
| `timestamp` | `TIMESTAMPTZ` | NO | When completion occurred (UTC) — from bot payload |
| `received_at` | `TIMESTAMPTZ` | NO | When the API ingested it — set by API as `NOW()`, never in payload |
| `command_name` | `VARCHAR(100)` | NO | Always present on completions |
| `status` | `VARCHAR(20)` | NO | `success`, `user_error`, or `internal_error` |
| `duration_ms` | `NUMERIC(10,2)` | YES | Command latency in milliseconds — measured bot-side with `time.monotonic()` |
| `error_type` | `VARCHAR(100)` | YES | Python exception class name (`type(error).__name__`); NULL on success |

### Interaction type reference

All possible values for `interaction_type`:

| Value | Source | Has completion? |
|-------|--------|----------------|
| `slash_command` | User invoked a slash command | Yes |
| `button` | User clicked a button component | No |
| `modal` | User submitted a modal form | No |
| `dropdown` | User selected from a select menu | No |
| `autocomplete` | User is typing a command argument | No — **should be filtered pre-Phase 3** |
| `component` | Component interaction, type unrecognised | No |
| `unknown` | Interaction type not in the type map | No |

### Design decisions

- **No FK constraint between tables** — soft join via `correlation_id`. Avoids constraint failures if events arrive out of order or a completion has no matching interaction.
- **`BIGINT` for Discord IDs** — Discord snowflakes are 64-bit integers and exceed `INTEGER` max.
- **`JSONB` for `options`** — flexible, queryable, stored in Postgres binary format.
- **`TIMESTAMPTZ` everywhere** — always timezone-aware, always stored as UTC.
- **`BIGSERIAL` for surrogate PKs** — auto-increment; the bot never generates these.
- **`CHECK` constraint on `status`** — the DB enforces the valid set, not just the API layer.
- **`received_at` on both tables** — enables independent API ingestion lag measurement per event type (`received_at - timestamp`).
- **`guild_name` stored, `username` not** — guild name is captured as historical context at event time. Guild names rarely change; storing the name makes logs readable without a Discord API lookup. Username changes frequently and is omitted; `user_id` is the stable identifier.
- **`bot_version` on interactions only** — version cannot change between an interaction and its completion (same process, milliseconds apart). Get it from the interaction row via the join.

---

## Indexes

6 indexes total — added only for queries that are actually run.

```sql
-- telemetry_interactions
CREATE INDEX idx_interactions_timestamp      ON telemetry_interactions (timestamp);
CREATE INDEX idx_interactions_correlation_id ON telemetry_interactions (correlation_id);
CREATE INDEX idx_interactions_command_name   ON telemetry_interactions (command_name, timestamp) WHERE command_name IS NOT NULL;

-- telemetry_completions
CREATE INDEX idx_completions_timestamp       ON telemetry_completions (timestamp);
CREATE INDEX idx_completions_correlation_id  ON telemetry_completions (correlation_id);
CREATE INDEX idx_completions_command_status  ON telemetry_completions (command_name, status);
```

Indexes on `user_id`, `guild_id`, `interaction_type`, and `error_type` are intentionally omitted. Each index slows every INSERT. Add them only when a real slow query demonstrates the need.

---

## DDL

See [`db/schema.sql`](../db/schema.sql) for the full, runnable DDL.

---

## Ingestion Write API

This section specifies `POST /api/v1/telemetry/batch` from the **API gateway's perspective** — what it accepts, how it validates, what it writes, and what it returns. The bot side (what it sends and why) is covered in [API Payload](#api-payload) below.

### Authentication

The write endpoint requires a static API key. The GET dashboard endpoints are unauthenticated (internal service, not publicly exposed).

**How it works:**

The API key is set as an environment variable on the server and read by the bot at startup. On every POST request, the bot sends it as a Bearer token. The API validates it against the env var — if it doesn't match, the request is rejected `401`.

| Location | Variable | Notes |
|---|---|---|
| API gateway `.env` | `TELEMETRY_API_KEY` | The authoritative key; set once, never committed to source control |
| Bot `.env` | `TELEMETRY_API_KEY` | Must match the gateway's value |

The `config.py` `Settings` class on the backend must be updated to read this variable:
```python
telemetry_api_key: str = ""   # empty string disables auth check in dev
```

If `TELEMETRY_API_KEY` is empty on the server, auth is skipped (dev/mock mode only). In production it must be set.

---

### `GET /api/v1/health`

Used by the bot to verify the API is reachable before starting its flush loop, and by ops to check service status.

**No authentication required.**

**Response: `200 OK`**

```json
{ "status": "ok", "mock": false }
```

| Field | Type | Notes |
|---|---|---|
| `status` | `str` | Always `"ok"` if the service is running |
| `mock` | `bool` | `true` when `USE_MOCK=true` in `.env` — indicates no real DB is connected |

The bot should call this endpoint once at startup. If it returns non-200 or times out, the bot should log a warning and skip telemetry for that session rather than erroring out.

---

### `POST /api/v1/telemetry/batch`

Receives a batch of mixed interaction and completion events from the bot and writes them to Postgres.

**Request**

```
POST /api/v1/telemetry/batch
Content-Type: application/json
Authorization: Bearer <api_key>
```

**Request body**

```json
{
  "events": [ ...event objects... ]
}
```

Top-level validation — reject `400` if:
- Body is not valid JSON
- `events` key is missing
- `events` is not an array

**Per-event validation**

Each event object must have a `"type"` field. The API routes it to the appropriate table based on this value.

| `type` value | Target table | Required fields |
|---|---|---|
| `"interaction"` | `telemetry_interactions` | `correlation_id`, `timestamp`, `interaction_type`, `user_id`, `channel_id`, `options`, `bot_version` |
| `"completion"` | `telemetry_completions` | `correlation_id`, `timestamp`, `command_name`, `status` |
| anything else | — | Rejected with error message |

Missing a required field → event is **rejected** (not the whole batch). Optional fields (`command_name`, `guild_id`, `guild_name` on interactions; `duration_ms`, `error_type` on completions) default to `null` if absent.

**Field constraints enforced by the API layer**

| Field | Constraint |
|---|---|
| `correlation_id` | Exactly 12 hex characters (`[0-9a-f]{12}`) |
| `timestamp` | Valid ISO 8601 datetime string; must include UTC offset |
| `interaction_type` | One of: `slash_command`, `button`, `modal`, `dropdown`, `component`, `autocomplete`, `unknown` |
| `user_id` | Integer, positive |
| `channel_id` | Integer, positive |
| `status` | One of: `success`, `user_error`, `internal_error` |
| `duration_ms` | Positive number if present; `null` allowed |

**INSERT SQL — interaction event**

```sql
INSERT INTO telemetry_interactions (
    correlation_id,
    timestamp,
    received_at,
    interaction_type,
    user_id,
    command_name,
    guild_id,
    guild_name,
    channel_id,
    options,
    bot_version
) VALUES (
    %(correlation_id)s,
    %(timestamp)s,
    NOW(),
    %(interaction_type)s,
    %(user_id)s,
    %(command_name)s,      -- nullable
    %(guild_id)s,          -- nullable
    %(guild_name)s,        -- nullable
    %(channel_id)s,
    %(options)s,           -- JSONB, defaults to '{}'
    %(bot_version)s
);
```

**INSERT SQL — completion event**

```sql
INSERT INTO telemetry_completions (
    correlation_id,
    timestamp,
    received_at,
    command_name,
    status,
    duration_ms,
    error_type
) VALUES (
    %(correlation_id)s,
    %(timestamp)s,
    NOW(),
    %(command_name)s,
    %(status)s,
    %(duration_ms)s,       -- nullable
    %(error_type)s         -- nullable
);
```

`received_at` is set to `NOW()` by the API on both inserts — never taken from the payload.

**Processing order**

Events are processed in the order they appear in the `events` array. A failure on one event does not stop processing of subsequent events — the batch continues and the rejection is recorded.

**Response**

| Scenario | HTTP status | Body |
|---|---|---|
| All events written | `202 Accepted` | `{ "written": <n> }` |
| Partial failure (some events invalid) | `202 Accepted` | `{ "written": <n>, "rejected": <m>, "errors": [...] }` |
| Malformed JSON or missing `events` key | `400 Bad Request` | `{ "error": "..." }` |
| Auth failure | `401 Unauthorized` | `{ "error": "..." }` |
| Server error | `500 Internal Server Error` | `{ "error": "..." }` |

**`errors` array format (partial failure)**

```json
{
  "written": 8,
  "rejected": 2,
  "errors": [
    { "index": 2, "reason": "missing required field: correlation_id" },
    { "index": 7, "reason": "invalid status value: 'failed'" }
  ]
}
```

`index` is the 0-based position of the rejected event in the original `events` array.

**Bot behaviour on non-2xx:** log a warning, do not retry, do not crash. Telemetry loss is acceptable; bot availability is not.

---

## API Payload

The bot POSTs a batch of events to the API gateway. `id` and `received_at` are never in the payload — they are set server-side.

### Endpoint

```
POST /api/v1/telemetry/batch
Content-Type: application/json
Authorization: Bearer <api_key>   (scheme TBD)
```

### Request body

```json
{
  "events": [ ...event objects... ]
}
```

Each object has a `"type"` field (`"interaction"` or `"completion"`) that tells the API which table to write to. A single batch may contain a mix of both types in the order they were emitted.

### Interaction event — slash command

```json
{
  "type": "interaction",
  "correlation_id": "a3f9c1d20b4e",
  "timestamp": "2026-03-20T14:23:01.123456+00:00",
  "interaction_type": "slash_command",
  "user_id": 123456789012345678,
  "command_name": "ping",
  "guild_id": 987654321098765432,
  "guild_name": "CAPY Server",
  "channel_id": 111222333444555666,
  "options": {},
  "bot_version": "0.1.0"
}
```

### Interaction event — slash command with arguments

`options` is a flat dict. Subcommand arguments are dot-prefixed (`"subcommand.arg"`). Discord mention types (User, Role, Channel) are serialised to their snowflake ID.

```json
{
  "type": "interaction",
  "correlation_id": "b7e2d4f81c9a",
  "timestamp": "2026-03-20T14:24:00.000000+00:00",
  "interaction_type": "slash_command",
  "user_id": 234567890123456789,
  "command_name": "profile",
  "guild_id": 987654321098765432,
  "guild_name": "CAPY Server",
  "channel_id": 111222333444555666,
  "options": { "action": "view" },
  "bot_version": "0.1.0"
}
```

### Interaction event — button (DM, no guild)

`command_name` will be `null` once the Phase 3 fix is applied (see work items). `custom_id` is in `options`.

```json
{
  "type": "interaction",
  "correlation_id": "c1a3b5d7e9f0",
  "timestamp": "2026-03-20T14:25:00.000000+00:00",
  "interaction_type": "button",
  "user_id": 345678901234567890,
  "command_name": null,
  "guild_id": null,
  "guild_name": null,
  "channel_id": 222333444555666777,
  "options": { "custom_id": "confirm_action" },
  "bot_version": "0.1.0"
}
```

### Interaction event — modal submit

`options` contains each form field keyed by its `custom_id`.

```json
{
  "type": "interaction",
  "correlation_id": "e5f7a9b1c3d2",
  "timestamp": "2026-03-20T14:26:00.000000+00:00",
  "interaction_type": "modal",
  "user_id": 234567890123456789,
  "command_name": null,
  "guild_id": 987654321098765432,
  "guild_name": "CAPY Server",
  "channel_id": 111222333444555666,
  "options": { "reason": "This is my feedback text" },
  "bot_version": "0.1.0"
}
```

### Completion event — success

```json
{
  "type": "completion",
  "correlation_id": "a3f9c1d20b4e",
  "timestamp": "2026-03-20T14:23:01.232456+00:00",
  "command_name": "ping",
  "status": "success",
  "duration_ms": 109.3
}
```

### Completion event — failure

`error_type` is the Python exception class name (`type(error).__name__`). `CommandInvokeError` is unwrapped to its `.original` before classification and naming.

```json
{
  "type": "completion",
  "correlation_id": "d4e6f8a0b2c3",
  "timestamp": "2026-03-20T14:27:01.052456+00:00",
  "command_name": "event",
  "status": "internal_error",
  "duration_ms": 52.0,
  "error_type": "RuntimeError"
}
```

Status values and their meaning:

| `status` | Set when |
|----------|---------|
| `success` | `on_app_command_completion` fires |
| `user_error` | Error is an instance of `UserFriendlyError` |
| `internal_error` | Any other exception |

### Field mapping — payload → database

| Payload field | `telemetry_interactions` | `telemetry_completions` |
|---------------|--------------------------|-------------------------|
| `correlation_id` | `correlation_id` | `correlation_id` |
| `timestamp` | `timestamp` | `timestamp` |
| `interaction_type` | `interaction_type` | — |
| `user_id` | `user_id` | — |
| `command_name` | `command_name` | `command_name` |
| `guild_id` | `guild_id` | — |
| `guild_name` | `guild_name` | — |
| `channel_id` | `channel_id` | — |
| `options` | `options` | — |
| `bot_version` | `bot_version` | — |
| `status` | — | `status` |
| `duration_ms` | — | `duration_ms` |
| `error_type` | — | `error_type` |
| *(set by API)* | `received_at` | `received_at` |
| *(set by DB)* | `id` | `id` |

### API response

| Scenario | HTTP status | Body |
|----------|-------------|------|
| All events written | `202 Accepted` | `{ "written": <n> }` |
| Partial failure (some events invalid) | `202 Accepted` | `{ "written": <n>, "rejected": <m>, "errors": [...] }` |
| Malformed JSON or missing `events` key | `400 Bad Request` | `{ "error": "..." }` |
| Auth failure | `401 Unauthorized` | `{ "error": "..." }` |
| Server error | `500 Internal Server Error` | `{ "error": "..." }` |

The bot should treat any non-2xx response as a transient failure and log a warning. Telemetry failures must never crash or block the bot.

---

## Key Queries

These are the queries the API gateway runs to power telemetry endpoints.

### Top commands (`GET /api/v1/commands`)

```sql
SELECT
    i.command_name,
    COUNT(i.id)                                                          AS invocations,
    ROUND(AVG(c.duration_ms), 1)                                        AS avg_latency_ms,
    ROUND(
        SUM(CASE WHEN c.status = 'success' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(c.id), 0), 2
    )                                                                    AS success_rate
FROM telemetry_interactions i
LEFT JOIN telemetry_completions c ON i.correlation_id = c.correlation_id
WHERE i.timestamp > NOW() - INTERVAL '30 days'
  AND i.command_name IS NOT NULL
GROUP BY i.command_name
ORDER BY invocations DESC
LIMIT 10;
```

### Unique users (`totals.unique_users`)

```sql
SELECT COUNT(DISTINCT user_id)
FROM telemetry_interactions
WHERE timestamp > NOW() - INTERVAL '30 days';
```

### Error breakdown (`top_errors`)

```sql
SELECT error_type, COUNT(*) AS count
FROM telemetry_completions
WHERE timestamp > NOW() - INTERVAL '30 days'
  AND error_type IS NOT NULL
GROUP BY error_type
ORDER BY count DESC;
```

### API ingestion lag

```sql
SELECT
    command_name,
    AVG(EXTRACT(EPOCH FROM (received_at - timestamp)) * 1000) AS avg_lag_ms
FROM telemetry_interactions
GROUP BY command_name;
```

---

## Dashboard Read API

The dashboard frontend (`Interactions-dashboard/`) consumes a separate set of read-only GET endpoints served by the FastAPI backend. All endpoints are under `/api/v1` and require no authentication (internal service). All metrics are **cross-guild totals** — no per-guild breakdown.

### Common query parameter

All endpoints except `/recent` accept:

| Parameter | Values | Default | Description |
|-----------|--------|---------|-------------|
| `range` | `24h`, `7d`, `30d` | `7d` | Time window for the query |

`range` maps to days internally: `24h` → 1 day, `7d` → 7 days, `30d` → 30 days.

---

### `GET /api/v1/metrics`

Summary KPIs for the four metric cards at the top of the dashboard. Includes percent-change vs. the prior equivalent period (e.g. for `7d`, compares the current 7 days against the 7 days before that).

**Response model: `MetricSummary`**

```json
{
  "total_interactions": 847,
  "unique_users": 62,
  "success_rate": 0.9412,
  "avg_latency_ms": 143.7,
  "total_interactions_change": 12.4,
  "unique_users_change": -3.1,
  "success_rate_change": 0.8,
  "avg_latency_change": -5.2
}
```

| Field | Type | Notes |
|-------|------|-------|
| `total_interactions` | `int` | All interaction rows in the window |
| `unique_users` | `int` | `COUNT(DISTINCT user_id)` |
| `success_rate` | `float` | 0.0–1.0; ratio of success completions to all completions |
| `avg_latency_ms` | `float` | Average `duration_ms` across all completions in window |
| `*_change` | `float` | Percent change vs. prior period; can be negative |

**SQL:**
```sql
-- Current period
SELECT
    COUNT(i.id)                                                              AS total_interactions,
    COUNT(DISTINCT i.user_id)                                                AS unique_users,
    ROUND(SUM(CASE WHEN c.status = 'success' THEN 1 ELSE 0 END)::numeric
          / NULLIF(COUNT(c.id), 0), 4)                                       AS success_rate,
    ROUND(AVG(c.duration_ms), 1)                                             AS avg_latency_ms
FROM telemetry_interactions i
LEFT JOIN telemetry_completions c ON i.correlation_id = c.correlation_id
WHERE i.timestamp > NOW() - (%s || ' days')::INTERVAL;

-- Prior period (run with range_days * 2, then subtract current window in app layer)
```

---

### `GET /api/v1/commands`

Top 10 commands by invocation count, with latency and success rate per command. Powers the command table.

**Response model: `list[CommandStat]`**

```json
[
  {
    "command_name": "profile",
    "invocations": 213,
    "avg_latency_ms": 157.4,
    "success_rate": 0.9718
  },
  {
    "command_name": "ping",
    "invocations": 98,
    "avg_latency_ms": 42.1,
    "success_rate": 1.0
  }
]
```

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `command_name` | `str` | NO | Slash command name |
| `invocations` | `int` | NO | Total rows for this command in window |
| `avg_latency_ms` | `float` | YES | `null` if no completions with duration |
| `success_rate` | `float` | YES | `null` if no completions; 0.0–1.0 |

**SQL:**
```sql
SELECT
    i.command_name,
    COUNT(i.id)                                                              AS invocations,
    ROUND(AVG(c.duration_ms), 1)                                             AS avg_latency_ms,
    ROUND(SUM(CASE WHEN c.status = 'success' THEN 1 ELSE 0 END)::numeric
          / NULLIF(COUNT(c.id), 0), 4)                                       AS success_rate
FROM telemetry_interactions i
LEFT JOIN telemetry_completions c ON i.correlation_id = c.correlation_id
WHERE i.timestamp > NOW() - (%s || ' days')::INTERVAL
  AND i.command_name IS NOT NULL
GROUP BY i.command_name
ORDER BY invocations DESC
LIMIT 10;
```

---

### `GET /api/v1/timeseries`

Interaction counts per time bucket, broken down by type. Powers the time series line chart.

**Bucket granularity depends on `range`:**

| `range` | Bucket | SQL truncation | `timestamp` format |
|---------|--------|----------------|--------------------|
| `24h` | Hour | `DATE_TRUNC('hour', timestamp)` | `"2026-03-20T14:00"` |
| `7d` | Day | `DATE_TRUNC('day', timestamp)` | `"2026-03-20"` |
| `30d` | Day | `DATE_TRUNC('day', timestamp)` | `"2026-03-20"` |

For `24h`, the response contains up to 24 points. For `7d`/`30d`, up to 7 or 30 points. Days/hours with zero interactions are **omitted** (not zero-filled) — the frontend handles sparse data.

**Response model: `list[TimeSeriesPoint]`**

```json
[
  { "timestamp": "2026-03-20T09:00", "slash_command": 8, "button": 3, "modal": 1 },
  { "timestamp": "2026-03-20T10:00", "slash_command": 12, "button": 2, "modal": 0 }
]
```

| Field | Type | Notes |
|-------|------|-------|
| `timestamp` | `str` | ISO format; hour precision for `24h`, date precision otherwise |
| `slash_command` | `int` | Count of `slash_command` interactions in bucket |
| `button` | `int` | Count of `button` interactions in bucket |
| `modal` | `int` | Count of `modal` interactions in bucket |

`dropdown` and `unknown` types are excluded from the pivot (negligible volume, no dedicated chart series).

**SQL:**
```sql
-- 24h (hourly)
SELECT
    DATE_TRUNC('hour', timestamp) AS bucket,
    interaction_type,
    COUNT(*)                       AS count
FROM telemetry_interactions
WHERE timestamp > NOW() - INTERVAL '1 day'
GROUP BY bucket, interaction_type
ORDER BY bucket;

-- 7d / 30d (daily)
SELECT
    DATE_TRUNC('day', timestamp) AS bucket,
    interaction_type,
    COUNT(*)                      AS count
FROM telemetry_interactions
WHERE timestamp > NOW() - (%s || ' days')::INTERVAL
GROUP BY bucket, interaction_type
ORDER BY bucket;
```

The backend pivots the result rows into one `TimeSeriesPoint` per bucket before returning.

---

### `GET /api/v1/errors`

Error type breakdown for the selected window. Powers the error breakdown panel. Only rows where `error_type IS NOT NULL` are included (i.e., `internal_error` completions only — `user_error` completions have `error_type = NULL`).

**Response model: `list[ErrorStat]`**

```json
[
  { "error_type": "RuntimeError", "count": 14 },
  { "error_type": "PermissionError", "count": 5 }
]
```

| Field | Type | Notes |
|-------|------|-------|
| `error_type` | `str` | Python exception class name |
| `count` | `int` | Occurrences in window |

**SQL:**
```sql
SELECT error_type, COUNT(*) AS count
FROM telemetry_completions
WHERE timestamp > NOW() - (%s || ' days')::INTERVAL
  AND error_type IS NOT NULL
GROUP BY error_type
ORDER BY count DESC;
```

---

### `GET /api/v1/interaction-types`

Total counts per interaction type for the selected window. Powers the interaction type donut/bar chart.

**Response model: `list[InteractionTypeStat]`**

```json
[
  { "interaction_type": "slash_command", "count": 594 },
  { "interaction_type": "button", "count": 168 },
  { "interaction_type": "modal", "count": 85 }
]
```

| Field | Type | Notes |
|-------|------|-------|
| `interaction_type` | `str` | One of `slash_command`, `button`, `modal`, `dropdown`, `unknown` |
| `count` | `int` | Total in window |

**SQL:**
```sql
SELECT interaction_type, COUNT(*) AS count
FROM telemetry_interactions
WHERE timestamp > NOW() - (%s || ' days')::INTERVAL
GROUP BY interaction_type
ORDER BY count DESC;
```

---

### `GET /api/v1/recent`

The most recent 50 interactions, each joined with its completion row. No `range` parameter — always returns the latest activity regardless of time window. Powers the activity feed in Row 5 of the dashboard.

**Purpose:** Real-time observability. Use this to diagnose live bot health — see what commands are being run, identify failures as they happen, and spot error patterns before they accumulate.

**Auto-refresh:** The frontend polls this endpoint every **30 seconds**. The backend does not push — polling is sufficient given the low write volume of a Discord bot.

**Privacy:** `user_id` is masked at the API layer before the response leaves the backend. The raw Discord snowflake is never returned. Format: last 4 digits prefixed with `...` (e.g. `123456789012345678` → `"...5678"`).

**Response model: `list[RecentEvent]`**

```json
[
  {
    "timestamp": "2026-03-20T14:23:01.123456+00:00",
    "user_id": "...5678",
    "interaction_type": "slash_command",
    "command_name": "profile",
    "status": "success",
    "duration_ms": 109.3,
    "error_type": null
  },
  {
    "timestamp": "2026-03-20T14:22:45.000000+00:00",
    "user_id": "...3421",
    "interaction_type": "button",
    "command_name": null,
    "status": null,
    "duration_ms": null,
    "error_type": null
  },
  {
    "timestamp": "2026-03-20T14:21:10.000000+00:00",
    "user_id": "...9002",
    "interaction_type": "slash_command",
    "command_name": "event",
    "status": "internal_error",
    "duration_ms": 52.0,
    "error_type": "RuntimeError"
  }
]
```

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `timestamp` | `str` | NO | ISO 8601 with UTC offset; from `telemetry_interactions` |
| `user_id` | `str` | NO | Masked — last 4 digits of snowflake, prefixed with `...` |
| `interaction_type` | `str` | NO | `slash_command`, `button`, `modal`, etc. |
| `command_name` | `str` | YES | `null` for buttons and modals |
| `status` | `str` | YES | `success`, `user_error`, or `internal_error`; `null` for buttons/modals |
| `duration_ms` | `float` | YES | `null` for buttons/modals and any missed completions |
| `error_type` | `str` | YES | Python exception class name; `null` on success or non-command interactions |

**Nullability pattern:** `status`, `duration_ms`, and `error_type` are `null` whenever there is no matching completion row — i.e. for `button`, `modal`, and any `slash_command` whose completion was dropped or not yet received.

**SQL:**
```sql
SELECT
    i.timestamp,
    i.user_id,
    i.interaction_type,
    i.command_name,
    c.status,
    c.duration_ms,
    c.error_type
FROM telemetry_interactions i
LEFT JOIN telemetry_completions c ON i.correlation_id = c.correlation_id
ORDER BY i.timestamp DESC
LIMIT 50;
```

**Backend masking (applied in the Python layer before serialisation):**
```python
def _mask_user_id(user_id: int) -> str:
    return "..." + str(user_id)[-4:]
```

---

### Dashboard endpoint summary

| Endpoint | Method | Range param | Refresh | Powers |
|----------|--------|-------------|---------|--------|
| `/api/v1/metrics` | GET | ✓ | On range change | Metric cards (Row 1) |
| `/api/v1/timeseries` | GET | ✓ | On range change | Time series chart (Row 2) |
| `/api/v1/commands` | GET | ✓ | On range change | Command table (Row 3 left) |
| `/api/v1/errors` | GET | ✓ | On range change | Error breakdown (Row 3 right) |
| `/api/v1/interaction-types` | GET | ✓ | On range change | Interaction type chart (Row 4) |
| `/api/v1/recent` | GET | ✗ | Every 30 seconds | Activity feed (Row 5) |

---

## Phase 3 Work Items

These are known gaps between the current bot code and what Phase 3 requires. All are small, targeted changes to `telemetry.py`.

### 1. Add `bot_version` to the interaction payload

`bot_version` is in the schema and required by the API, but `_extract_interaction_data` does not include it. The bot needs to read its version from config and inject it:

```python
# In _extract_interaction_data, add:
"bot_version": self.bot.version,  # or however the bot exposes its version
```

### 2. Fix `command_name` for non-command interactions

`_get_command_name` currently falls back to `interaction.data.get("custom_id")` for buttons and dropdowns. This puts the `custom_id` in `command_name`, which is wrong — `command_name` is for slash command names only. `custom_id` is already captured in `options` via `_extract_interaction_options`. The fix is to return `None` for non-command interactions:

```python
def _get_command_name(self, interaction):
    if interaction.command:
        return interaction.command.name
    return None  # custom_id belongs in options, not command_name
```

### 3. Filter out `autocomplete` interactions

Autocomplete fires on every keystroke while a user types a slash command argument. Storing these adds noise with no analytical value. Filter them before enqueuing:

```python
# In on_interaction, add early return:
if interaction.type == discord.InteractionType.autocomplete:
    return
```

### 4. Remove `username` from the event dict

`_extract_interaction_data` includes `"username": str(interaction.user)`. Since `username` is not in the schema, the API must currently ignore this field. For cleanliness, remove it from the extraction:

```python
# Remove this line from _extract_interaction_data:
"username": str(interaction.user),
```

### 5. Wire the queue consumer to POST to the API

The current consumer dispatches events to in-memory metrics and logging. In Phase 3, the consumer (or a separate flush task) should batch the queue contents and call `POST /api/v1/telemetry/batch`. The in-memory metrics path can remain in parallel — they serve different purposes (real-time `/stats` command vs. persistent historical data).

---

## What the Bot Does NOT Do

- Connect to the database directly
- Run migrations
- Generate surrogate PKs (`id`) or ingestion timestamps (`received_at`) — both are set server-side
- Store usernames (`username` is extracted internally but excluded from the schema and will be removed from the payload in Phase 3)
