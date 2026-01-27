import logging
from collections.abc import Callable
from typing import Any, TypeVar

import discord
from discord import ui
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from capy_discord.ui.modal import BaseModal

T = TypeVar("T", bound=BaseModel)

MAX_DISCORD_ROWS = 5
MAX_TEXT_INPUT_LEN = 4000
MAX_PLACEHOLDER_LEN = 100


class RetryView[T: BaseModel](ui.View):
    """A view that allows a user to retry a failed form submission."""

    def __init__(
        self,
        model_cls: type[T],
        callback: Callable[[discord.Interaction, T], Any],
        title: str,
        initial_data: dict[str, Any],
    ) -> None:
        """Initialize the RetryView."""
        super().__init__(timeout=300)
        self.model_cls = model_cls
        self.callback = callback
        self.title = title
        self.initial_data = initial_data

    @ui.button(label="Fix Errors", style=discord.ButtonStyle.red, emoji="🔧")
    async def retry(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Open the modal again with pre-filled values."""
        modal = ModelModal(
            model_cls=self.model_cls, callback=self.callback, title=self.title, initial_data=self.initial_data
        )
        await interaction.response.send_modal(modal)


class ModelModal[T: BaseModel](BaseModal):
    """A modal generated automatically from a Pydantic model."""

    def __init__(
        self,
        model_cls: type[T],
        callback: Callable[[discord.Interaction, T], Any],
        title: str,
        initial_data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize the ModelModal.

        Args:
            model_cls: The Pydantic model class defining the form schema.
            callback: Function to call with the validated model instance on success.
            title: The title of the modal.
            initial_data: Optional dictionary to pre-fill fields (used for retries).
            timeout: The timeout in seconds.
        """
        super().__init__(title=title, timeout=timeout)
        self.model_cls = model_cls
        self.callback = callback
        self.log = logging.getLogger(__name__)

        # Discord Modals are limited to 5 ActionRows (items)
        if len(self.model_cls.model_fields) > MAX_DISCORD_ROWS:
            msg = (
                f"Model '{self.model_cls.__name__}' has {len(self.model_cls.model_fields)} fields, "
                "but Discord modals only support a maximum of 5."
            )
            raise ValueError(msg)

        self._inputs: dict[str, ui.TextInput] = {}
        self._generate_fields(initial_data or {})

    def _generate_fields(self, initial_data: dict[str, Any]) -> None:
        """Generate UI components from the Pydantic model fields."""
        for name, field_info in self.model_cls.model_fields.items():
            # Determine default/initial value
            # Priority: initial_data > field default
            default_value = initial_data.get(name)

            if (
                default_value is None
                and field_info.default is not None
                and field_info.default is not PydanticUndefined
                and isinstance(field_info.default, (str, int, float))
            ):
                default_value = str(field_info.default)

            # Determine constraints from Pydantic metadata
            max_len = None
            min_len = None
            max_len_thresh = 100

            for metadata in field_info.metadata:
                if hasattr(metadata, "max_length"):
                    max_len = metadata.max_length
                if hasattr(metadata, "min_length"):
                    min_len = metadata.min_length

            # Determine Label (Title) and Placeholder (Description)
            label = field_info.title or name.replace("_", " ").title()
            placeholder = field_info.description or f"Enter {label}..."

            # Create the input
            # Note: Discord TextInput max_length is 4000
            text_input = ui.TextInput(
                label=label[:45],
                placeholder=placeholder[:MAX_PLACEHOLDER_LEN],
                default=str(default_value) if default_value else None,
                required=field_info.is_required(),
                max_length=min(max_len, MAX_TEXT_INPUT_LEN) if max_len else MAX_TEXT_INPUT_LEN,
                min_length=min_len,
                style=(
                    discord.TextStyle.paragraph if (max_len and max_len > max_len_thresh) else discord.TextStyle.short
                ),
                row=len(self._inputs) if len(self._inputs) < MAX_DISCORD_ROWS else 4,
            )

            self.add_item(text_input)
            self._inputs[name] = text_input

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate inputs and trigger callback or retry flow."""
        raw_data = {name: inp.value for name, inp in self._inputs.items()}

        try:
            # Attempt to instantiate and validate the Pydantic model
            validated_instance = self.model_cls(**raw_data)

            # If successful, call the user's callback with the clean data object
            await self.callback(interaction, validated_instance)

        except ValidationError as e:
            # Validation Failed
            error_messages = []
            for err in e.errors():
                loc = str(err["loc"][0])
                msg = err["msg"].replace("Value error, ", "")  # Cleanup common pydantic prefix
                error_messages.append(f"• **{loc}**: {msg}")

            error_text = "\n".join(error_messages)

            # create retry view with preserved input
            view = RetryView(model_cls=self.model_cls, callback=self.callback, title=self.title, initial_data=raw_data)

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ **Validation Failed**\n{error_text}", ephemeral=True, view=view
                )
            else:
                await interaction.followup.send(f"❌ **Validation Failed**\n{error_text}", ephemeral=True, view=view)
