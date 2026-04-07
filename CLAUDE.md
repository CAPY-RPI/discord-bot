# Claude Code Guide — capy-discord

## Instructions for Claude
At the end of every conversation, update this file with any new knowledge gained:
- New patterns, conventions, or decisions made during the session
- Bugs found and how they were resolved
- New files, modules, or features added
- Any preferences or workflow notes from the user

Keep additions concise and placed in the relevant section. If no relevant section exists, create one.

## Project Overview
A Discord bot built with `discord.py`. Extensions live in `capy_discord/exts/` and follow a modular cog-based architecture.

## Commands
- **Start**: `uv run task start`
- **Lint**: `uv run task lint` — run before every commit
- **Test**: `uv run task test`

Always use `uv` to run commands.

## Directory Structure
```
capy_discord/
├── exts/
│   ├── guild.py            # Simple Cog
│   ├── tools/              # Grouping directory
│   ├── profile/            # Complex feature directory
│   │   ├── profile.py      # Main cog (matches directory name)
│   │   ├── _schemas.py     # Helper — underscore prefix required
│   │   └── _views.py       # Helper — underscore prefix required
│   └── __init__.py
├── ui/
│   ├── forms.py            # ModelModal
│   ├── views.py            # BaseView
│   └── modal.py            # Low-level base classes
└── bot.py
```

Helper files inside feature folders **must be prefixed with `_`** to prevent the extension loader from treating them as cogs.

## UI Patterns

### Forms — `ModelModal`
Use for data collection. Auto-generates forms from Pydantic models with built-in validation and retry.
```python
from capy_discord.ui.forms import ModelModal
modal = ModelModal(MyModel, callback=self.handler, title="Title")
await interaction.response.send_modal(modal)
```

### Interactive Views — `BaseView`
Always inherit from `BaseView` instead of `discord.ui.View`.
```python
from capy_discord.ui.views import BaseView
class MyView(BaseView):
    @discord.ui.button(label="Click")
    async def on_click(self, interaction, button): ...
```

### Simple Inputs — `CallbackModal`
For one-off inputs where a full Pydantic model is overkill.
```python
from capy_discord.ui.modal import CallbackModal
modal = CallbackModal(callback=my_handler, title="Quick Input")
```

## Command Patterns
- **Single resource (CRUD)**: Use one command with `app_commands.choices`.
- **Complex features**: Use `commands.GroupCog`.

## Cog Standards
All Cogs **must** accept `bot` in `__init__`. Do not use `capy_discord.instance` (deprecated).
```python
class MyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))
```

## Error Handling
A global `on_tree_error` handler in `bot.py` covers most cases. Do not wrap every command in `try/except` — only catch specific business logic errors.

## Logging
```python
import logging
self.log = logging.getLogger(__name__)
```
Format: `[{asctime}] [{levelname:<8}] {name}: {message}` — always use `__name__`.

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
