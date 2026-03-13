# Phase 3 — Telemetry API & Database

## Overview

The bot never connects to the database directly. It POSTs batches of telemetry events to an API gateway, which owns the database. This document defines the PostgreSQL schema that the API gateway uses to store those events.

---

## Schema

Two append-only tables. The bot emits two event types per slash command — an **interaction** (captured the moment the command fires) and a **completion** (captured when it resolves, with outcome and latency). Buttons and modals emit an interaction only, since `on_app_command_completion` does not fire for them.

### `telemetry_interactions`

One row per Discord interaction (slash command, button click, modal submit, dropdown).

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | `BIGSERIAL` | NO | Auto-incrementing surrogate PK |
| `correlation_id` | `VARCHAR(12)` | NO | 12-char hex; links to completions |
| `timestamp` | `TIMESTAMPTZ` | NO | When the interaction occurred (UTC) |
| `received_at` | `TIMESTAMPTZ` | NO | When the API ingested it; defaults to `NOW()` |
| `interaction_type` | `VARCHAR(20)` | NO | `slash_command`, `button`, `modal`, `dropdown` |
| `user_id` | `BIGINT` | NO | Discord snowflake — stable, immutable identifier |
| `command_name` | `VARCHAR(100)` | YES | NULL for buttons and modals |
| `guild_id` | `BIGINT` | YES | NULL in DMs |
| `guild_name` | `VARCHAR(100)` | YES | Guild name at time of event; NULL in DMs |
| `channel_id` | `BIGINT` | NO | Discord snowflake |
| `options` | `JSONB` | NO | Command args, modal field values, etc. Defaults to `{}` |
| `bot_version` | `VARCHAR(20)` | NO | Bot version at time of event; defaults to `'unknown'` |

**Why `guild_name` is stored but `username` is not:** `guild_name` is recorded as it was at the time of the event — this is intentional. Guild names rarely change, and storing the historical name makes logs readable without requiring a Discord API lookup. If a guild renames, old events correctly reflect the name it had at that time. `username`, by contrast, changes frequently and is omitted: `user_id` is the stable identifier, and usernames are closer to PII.

### `telemetry_completions`

One row per command outcome. Slash commands only — buttons and modals do not produce completion rows.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | `BIGSERIAL` | NO | Auto-incrementing surrogate PK |
| `correlation_id` | `VARCHAR(12)` | NO | Links to `telemetry_interactions` |
| `timestamp` | `TIMESTAMPTZ` | NO | When completion occurred (UTC) |
| `received_at` | `TIMESTAMPTZ` | NO | When the API ingested it; defaults to `NOW()` |
| `command_name` | `VARCHAR(100)` | NO | Always present on completions |
| `status` | `VARCHAR(20)` | NO | `success`, `user_error`, or `internal_error` |
| `duration_ms` | `NUMERIC(10,2)` | YES | Command latency in milliseconds |
| `error_type` | `VARCHAR(100)` | YES | Python exception class name; NULL on success |

**Why `bot_version` is not on completions:** The bot version cannot change between an interaction and its completion — they occur in the same process within milliseconds. Version is available on the paired interaction row via `correlation_id`.

---

## Key Design Decisions

- **No FK constraint between tables** — soft join via `correlation_id`. Avoids failures if event ordering is non-deterministic at the API layer.
- **`BIGINT` for Discord IDs** — Discord snowflakes are 64-bit integers and exceed `INTEGER` max.
- **`JSONB` for `options`** — flexible, queryable, stored in Postgres binary format.
- **`TIMESTAMPTZ` everywhere** — always timezone-aware, always stored as UTC.
- **`BIGSERIAL` for surrogate PKs** — auto-increment; the bot never generates these.
- **`CHECK` constraint on `status`** — the DB enforces the valid set, not just the API layer.
- **`received_at` on both tables** — enables independent API ingestion lag measurement per event type.
- **`guild_name` stored, `username` not** — guild name is captured as historical context at event time. Username is omitted; `user_id` is the stable identifier.

---

## Indexes

6 indexes total — added only for queries the API gateway actually runs.

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

Additional indexes (e.g. `user_id`, `guild_id`, `interaction_type`, `error_type`) are intentionally omitted. Each index slows every INSERT. Add them only when a real slow query demonstrates the need.

---

## DDL

See [`db/schema.sql`](../db/schema.sql) for the full, runnable DDL.

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

## What the Bot Does NOT Do

- Connect to the database directly
- Run migrations
- Generate surrogate PKs
- Store usernames or guild names
