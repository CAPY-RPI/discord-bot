# Capy Discord Agent & Contributor Guide

This document outlines the architectural patterns, workflows, and standards for the `capy-discord` project. All agents and contributors must adhere to these guidelines to ensure scalability and code consistency.

## 1. Directory Structure

We follow a flexible modular structure within `capy_discord/exts/`.

### Guidelines
1.  **Feature Folders**: Complex features get their own directory (e.g., `exts/profile/`).
2.  **Internal Helpers**: Helper files in a feature folder (schemas, views) **must be prefixed with an underscore** (e.g., `_schemas.py`) to prevent the extension loader from treating them as cogs.
3.  **Grouping**: Use directories like `exts/tools/` to group simple, related cogs.
4.  **Single File Cogs**: Simple cogs can live directly in `exts/` or a grouping directory.

```text
capy_discord/
├── exts/
│   ├── guild.py            # Simple Cog
│   ├── tools/              # Grouping directory
│   │   ├── ping.py
│   │   └── sync.py
│   ├── profile/            # Complex Feature (Directory)
│   │   ├── profile.py      # Main Cog file (shares directory name)
│   │   ├── _schemas.py     # Helper (ignored by loader)
│   │   └── _views.py       # Helper (ignored by loader)
│   └── __init__.py
├── ui/
│   ├── forms.py            # ModelModal (Standard Forms)
│   ├── views.py            # BaseView (Standard Interactions)
│   └── modal.py            # Low-level base classes
└── bot.py
```

## 2. UI Patterns

We use high-level abstractions to eliminate boilerplate.

### Standard Forms (`ModelModal`)
**Use for:** Data collection and user input.
Do not subclass `BaseModal` manually for standard forms. Use `ModelModal` to auto-generate forms from Pydantic models.

*   **Auto-Generation**: Converts Pydantic fields to TextInputs.
*   **Validation**: Validates input against schema on submit.
*   **Retry**: Auto-handles validation errors with a "Fix Errors" flow.

```python
from capy_discord.ui.forms import ModelModal

class UserProfile(BaseModel):
    name: str = Field(title="Display Name", max_length=20)

# In your command:
modal = ModelModal(UserProfile, callback=self.save_profile, title="Edit Profile")
await interaction.response.send_modal(modal)
```

### Interactive Views (`BaseView`)
**Use for:** Buttons, Selects, and custom interactions.
Always inherit from `BaseView` instead of `discord.ui.View`.

*   **Safety**: Handles timeouts and errors automatically.
*   **Tracking**: Use `view.reply(interaction, ...)` to link view to message.

```python
from capy_discord.ui.views import BaseView

class ConfirmView(BaseView):
    @discord.ui.button(label="Confirm")
    async def confirm(self, interaction, button):
        ...
```

### Simple Inputs (`CallbackModal`)
**Use for:** Simple one-off inputs where a full Pydantic model is overkill.

```python
from capy_discord.ui.modal import CallbackModal
modal = CallbackModal(callback=my_handler, title="Quick Input")
```

## 3. Command Patterns

### Action Choices (CRUD)
For managing a single resource, use one command with `app_commands.choices`.

```python
@app_commands.choices(action=[
    Choice(name="create", value="create"),
    Choice(name="view", value="view"),
])
async def resource(self, interaction, action: str):
    ...
```

### Group Cogs
For complex features with multiple distinct sub-functions, use `commands.GroupCog`.

## 4. Error Handling
We use a global `on_tree_error` handler in `bot.py`.
*   Exceptions are logged with the specific module name.
*   Do not wrap every command in `try/except` blocks unless handling specific business logic errors.

## 5. Time and Timezones
**Always use `zoneinfo.ZoneInfo`**.
*   **Storage**: `UTC`.
*   **Usage**: `datetime.now(ZoneInfo("UTC"))`.

## 6. Development Workflow

### Linear & Branching
*   **Issue Tracking**: Every task must have a Linear issue.
*   **Branching**:
    *   `feature/CAPY-123-description`
    *   `fix/CAPY-123-description`
    *   `refactor/` | `docs/` | `test/`

### Dependency Management (`uv`)
Always run commands via `uv` to use the virtual environment.

*   **Start**: `uv run task start`
*   **Lint**: `uv run task lint` (Run this before every commit!)
*   **Test**: `uv run task test`

### Commit Guidelines (Conventional Commits)
Format: `<type>(<scope>): <subject>`

*   `feat(auth): add login flow`
*   `fix(ui): resolve timeout issue`
*   Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.

### Pull Requests
1.  **Base Branch**: Merge into `develop`.
2.  **Reviewers**: Must include `Shamik` and `Jason`.
3.  **Checks**: All CI checks (Lint, Test, Build) must pass.

## 7. Cog Standards

### Initialization
All Cogs **MUST** accept the `bot` instance in `__init__`. The use of the global `capy_discord.instance` is **deprecated** and should not be used in new code.

```python
class MyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))
```
