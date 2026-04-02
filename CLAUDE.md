# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> At the end of every conversation, update this file with any new knowledge gained: new patterns, bugs found, decisions made, new files/features added. Keep additions concise and in the relevant section.

## Commands

Always use `uv` to run commands.

- **Start**: `uv run task start`
- **Lint**: `uv run task lint` — run before every commit (installs pre-commit hooks + runs ruff)
- **Test**: `uv run task test` — runs pytest with parallelism, exits 0 if no tests collected
- **Retest**: `uv run task retest` — reruns only previously-failed tests
- **Single test**: `uv run pytest tests/path/to/test_file.py::test_name`
- **Docker build/run**: `uv run task build` / `uv run task run`

## Architecture

`Bot` (`capy_discord/bot.py`) extends `commands.AutoShardedBot`. On `setup_hook` it calls `load_extensions()`, which uses `capy_discord/utils/extensions.py` to auto-discover all cogs by walking `capy_discord.exts`. The loader skips any module whose dotted path contains a `_`-prefixed segment, and skips packages that lack a `setup()` function.

### Extension Layout

```
capy_discord/exts/
├── core/telemetry.py       # Always-loaded telemetry cog (see Telemetry below)
├── event/event.py          # Event announcement cog
├── guild/guild.py          # Guild management cog
├── profile/profile.py      # User profile cog
├── tickets/feedback.py     # Ticket/feedback cog
└── tools/                  # Utility commands (ping, sync, purge, notify, privacy, hotswap)
```

Helper files inside feature directories **must use a `_` prefix** (e.g., `_schemas.py`, `_views.py`) to prevent the extension loader from treating them as cogs.

### Configuration

`capy_discord/config.py` uses `pydantic-settings` to load from `.env`. Key settings:

| Variable | Default | Purpose |
|---|---|---|
| `TOKEN` | `""` | Discord bot token |
| `PREFIX` | `"/"` | Command prefix |
| `DEBUG_GUILD_ID` | `None` | Guild for instant slash command sync |
| `TICKET_FEEDBACK_CHANNEL_ID` | `0` | Channel for ticket feedback |
| `ANNOUNCEMENT_CHANNEL_NAME` | `"test-announcements"` | Event announcement channel |
| `TELEMETRY_API_URL` | `"http://localhost:8000"` | Interactions Dashboard API |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### Telemetry

`capy_discord/exts/core/telemetry.py` captures every interaction (slash commands, buttons, dropdowns, modals) via `on_interaction` and `on_app_command_completion`. Events are queued in an `asyncio.Queue` and flushed by a background `tasks.loop` that:
1. Updates in-memory `TelemetryMetrics` (counters, latency stats, unique users)
2. HTTP-POSTs event batches to `{TELEMETRY_API_URL}/api/v1/telemetry/batch` if the API was reachable at startup

`bot.py` calls `telemetry.log_command_failure(interaction, error)` from its error handler to track failures. Telemetry is designed to never crash the bot — all methods catch and log exceptions internally.

`Telemetry.get_metrics()` returns a deep-copy snapshot of in-memory metrics (used by analytics commands).

### Services Layer

`capy_discord/services/` contains shared, cog-independent logic:

- **`dm.py`** — `DirectMessenger` for safe bulk DMs. Compose a `Draft` via `compose()`, preview recipients, then `send()`. Enforces an audience `Policy` (allowlist of user/role IDs, recipient cap, blocks `@everyone`).
- **`policies.py`** — Convenience factories: `allow_users()`, `allow_roles()`, `allow_targets()`, `DENY_ALL`.

## Cog Standards

```python
class MyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.log = logging.getLogger(__name__)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))
```

- Do not use `capy_discord.instance` (deprecated).
- **Single resource (CRUD)**: one command with `app_commands.choices`.
- **Complex features**: `commands.GroupCog`.

## UI Patterns

### Embeds — `capy_discord/ui/embeds.py`
Use the standard helpers for consistent styling: `error_embed`, `success_embed`, `info_embed`, `warning_embed`, `important_embed`, `loading_embed`.

### Forms — `ModelModal`
Auto-generates Discord modals from Pydantic models (max 5 fields). Handles validation and retry flow.
```python
from capy_discord.ui.forms import ModelModal
modal = ModelModal(MyModel, callback=self.handler, title="Title")
await interaction.response.send_modal(modal)
```
Hide internal fields with `json_schema_extra={"ui_hidden": True}` on the Pydantic field.

### Interactive Views — `BaseView`
Always inherit from `BaseView` instead of `discord.ui.View`.
```python
from capy_discord.ui.views import BaseView
class MyView(BaseView):
    @discord.ui.button(label="Click")
    async def on_click(self, interaction, button): ...
```

### Simple Inputs — `CallbackModal`
```python
from capy_discord.ui.modal import CallbackModal
modal = CallbackModal(callback=my_handler, title="Quick Input")
```

## Error Handling

Raise `UserFriendlyError` for errors that should be shown to the user:
```python
from capy_discord.errors import UserFriendlyError
raise UserFriendlyError("internal log msg", user_message="Something went wrong.")
```
The global `on_tree_error` handler in `bot.py` catches these and sends an ephemeral error embed. Do not wrap every command in `try/except` — only catch specific business logic errors.

## Logging

```python
import logging
self.log = logging.getLogger(__name__)
```
Format: `[{asctime}] [{levelname:<8}] {name}: {message}` — always use `__name__`. Never use `print()`.

## Time & Timezones

Always use `zoneinfo.ZoneInfo`. Store in UTC.
```python
from zoneinfo import ZoneInfo
from datetime import datetime
datetime.now(ZoneInfo("UTC"))
```

## Git Workflow

- **Branches**: `feature/CAPY-123-description`, `fix/CAPY-123-description`, `refactor/`, `docs/`, `test/`
- **Commits**: Conventional Commits — `feat(scope): subject`, `fix(scope): subject`
  - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- **PRs**: Merge into `develop`. Reviewers: Shamik and Jason. All CI checks must pass.

## Related Projects

**Interactions Dashboard** — A separate FastAPI + Vite/React/Tailwind/Recharts telemetry dashboard that receives events from this bot via `TELEMETRY_API_URL`.
- Backend: port 8000, `USE_MOCK=true` in `.env` for development without Postgres.
- Frontend: `npm run dev` from `frontend/` (port 5173, proxies `/api` to backend).
- Database: `psycopg2` (sync). Mock data uses seed=42, ~1000 interactions over 30 days.

## Bugs Fixed & Lessons Learned

### FastAPI Router Prefix vs Route Path
**Rule:** Always verify full resolved URL = `include_router(prefix)` + `@router.route(path)`. The telemetry router is mounted at `/api/v1` with no sub-prefix, so routes must include `/telemetry/` in the path (e.g., `@router.post("/telemetry/batch")`).

### Postgres Schema Permissions
**Rule:** After `CREATE USER`, always grant schema access: `GRANT ALL ON SCHEMA public TO <user>;` before running `schema.sql`.

### Backend Startup (taskipy)
**Rule:** If `uv run task <name>` fails with "command not found", run the underlying command from `[tool.taskipy.tasks]` in `pyproject.toml` prefixed with `uv run` (e.g., `uv run uvicorn dashboard.main:app --reload --port 8000`).
