# Scalable Cog & Interaction Patterns

This document outlines the architectural patterns used in the `capy-discord` project to ensure scalability, clean code, and a consistent user experience. All agents and contributors should adhere to these patterns when creating new features.

## 1. Directory Structure

We follow a hybrid "Feature Folder" structure. Directories are created only as needed for complexity.

```
capy_discord/
├── exts/
│   ├── profile/          # Complex Feature (Directory)
│   │   ├── __init__.py   # Cog entry point
│   │   ├── schemas.py    # Feature-specific models
│   │   └── views.py      # Feature-specific UI
│   ├── ping.py           # Simple Feature (Standalone file)
│   └── __init__.py
├── ui/
│   ├── modal.py          # Shared UI components
│   ├── views.py          # BaseView and shared UI
│   └── ...
└── bot.py
```

## 2. The `CallbackModal` Pattern (Decoupled UI)

To prevent business logic from leaking into UI classes, we use the `CallbackModal` pattern. This keeps Modal classes "dumb" (pure UI/Validation) and moves logic into the Controller (Cog/Service).

### Usage

1.  **Inherit from `CallbackModal`**: located in `capy_discord.ui.modal`.
2.  **Field Limit**: **Discord modals can only have up to 5 fields.** If you need more data, consider using multiple steps or splitting the form.
3.  **Dynamic Initialization**: Use `__init__` to accept `default_values` for "Edit" flows.
3.  **Inject Logic**: Pass a `callback` function from your Cog that handles the submission.

**Example:**

```python
# In your Cog file
class MyModal(CallbackModal):
    def __init__(self, callback, default_text=None):
        super().__init__(callback=callback, title="My Modal")
        self.text_input = ui.TextInput(default=default_text, ...)
        self.add_item(self.text_input)

class MyCog(commands.Cog):
    ...
    async def my_command(self, interaction):
        modal = MyModal(callback=self.handle_submit)
        await interaction.response.send_modal(modal)

    async def handle_submit(self, interaction, modal):
        # Business logic here!
        value = modal.text_input.value
        await interaction.response.send_message(f"You said: {value}")
```

## 3. Command Structure (Single Entry Point)

To avoid cluttering the Discord command list, prefer a **Single Command with Choices** or **Subcommands** over multiple top-level commands.

### Pattern: Action Choices

Use `app_commands.choices` to route actions within a single command. This is preferred for CRUD operations on a single resource (e.g., `/profile`).

```python
@app_commands.command(name="resource", description="Manage resource")
@app_commands.describe(action="The action to perform")
@app_commands.choices(
    action=[
        app_commands.Choice(name="create", value="create"),
        app_commands.Choice(name="view", value="view"),
    ]
)
async def resource(self, interaction: discord.Interaction, action: str):
    if action == "create":
        await self.create_handler(interaction)
    elif action == "view":
        await self.view_handler(interaction)
```

## 4. Extension Loading

Extensions should be robustly discoverable. Our `extensions.py` utility supports deeply nested subdirectories.

- **Packages (`__init__.py` with `setup`)**: Loaded as a single extension.
- **Modules (`file.py`)**: Loaded individually.
- **Naming**: Avoid starting files/folders with `_` unless they are internal helpers.

## 5. Deployment & Syncing

- **Global Sync**: Done automatically on startup for consistent deployments.
- **Dev Guild**: A specific Dev Guild ID can be targeted for rapid testing and clearing "ghost" commands.
- **Manual Sync**: A `!sync` (text) command is available for emergency re-syncing without restarting.

## 6. Time and Timezones

To prevent bugs related to naive datetimes, **always use `zoneinfo.ZoneInfo`** for timezone-aware datetimes.

- **Default Timezone**: Use `UTC` for database storage and internal logic.
- **Library**: Use the built-in `zoneinfo` module (available in Python 3.9+).

**Example:**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

# Always specify tzinfo
now = datetime.now(ZoneInfo("UTC"))
```

## 7. Development Workflow

We use `uv` for dependency management and task execution. This ensures all commands run within the project's virtual environment.

### Running Tasks

Use `uv run task <task_name>` to execute common development tasks defined in `pyproject.toml`.

- **Start App**: `uv run task start`
- **Lint & Format**: `uv run task lint`
- **Run Tests**: `uv run task test`
- **Build Docker**: `uv run task build`

**IMPORTANT: After every change, run `uv run task lint` to perform a Ruff and Type check.**

### Running Scripts

To run arbitrary scripts or commands within the environment:

```bash
uv run python path/to/script.py
```

## 8. Git Commit Guidelines

### Pre-Commit Hooks

This project uses pre-commit hooks for linting. If a hook fails during commit:

1. **DO NOT** use `git commit --no-verify` to bypass hooks.
2. **DO** run `uv run task lint` manually to verify and fix issues.
3. If `uv run task lint` passes but the hook still fails (e.g., executable not found), there is likely an environment issue with the pre-commit config that needs to be fixed.

### Cog Initialization Pattern

All Cogs **MUST** accept the `bot` instance as an argument in their `__init__` method:

```python
# CORRECT
class MyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))

# INCORRECT - Do not use global instance or omit bot argument
class MyCog(commands.Cog):
    def __init__(self) -> None:  # Missing bot!
        pass
```

This ensures:
- Proper dependency injection
- Testability (can pass mock bot)
- No reliance on global state
