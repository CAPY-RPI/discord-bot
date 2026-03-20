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
POST /v1/telemetry/batch  ──►  API Gateway  ──►  PostgreSQL
                                                 ├── telemetry_interactions
                                                 └── telemetry_completions
```

The bot never connects to the database directly. The API gateway owns the database, validates payloads, and writes rows. The bot only POSTs batches.

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

## API Payload

The bot POSTs a batch of events to the API gateway. `id` and `received_at` are never in the payload — they are set server-side.

### Endpoint

```
POST /v1/telemetry/batch
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

### Top commands (`GET /v1/telemetry/metrics`)

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

The current consumer dispatches events to in-memory metrics and logging. In Phase 3, the consumer (or a separate flush task) should batch the queue contents and call `POST /v1/telemetry/batch`. The in-memory metrics path can remain in parallel — they serve different purposes (real-time `/stats` command vs. persistent historical data).

---

## What the Bot Does NOT Do

- Connect to the database directly
- Run migrations
- Generate surrogate PKs (`id`) or ingestion timestamps (`received_at`) — both are set server-side
- Store usernames (`username` is extracted internally but excluded from the schema and will be removed from the payload in Phase 3)
