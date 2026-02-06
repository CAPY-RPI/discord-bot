import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

import discord
from discord import ui
from discord.utils import MISSING
from pydantic import BaseModel

from capy_discord.ui.embeds import error_embed
from capy_discord.ui.forms import ModelModal

T = TypeVar("T", bound=BaseModel)


class BaseView(ui.View):
    """A base view class that handles common lifecycle events like timeouts.

    This class automatically manages:
    1. Disabling items on timeout.
    2. Tracking the message associated with the view.
    3. Handling errors in item callbacks.
    """

    def __init__(self, *, timeout: float | None = 180) -> None:
        """Initialize the BaseView."""
        super().__init__(timeout=timeout)
        self.message: discord.InteractionMessage | None = None
        self.log = logging.getLogger(__name__)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item) -> None:
        """Handle errors raised in view items."""
        self.log.error("Error in view %s item %s: %s", self, item, error, exc_info=error)

        embed = error_embed(description="Something went wrong!\nThe error has been logged for the developers.")

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self) -> None:
        """Disable all items and update the message on timeout."""
        self.log.info("View timed out: %s", self)
        self.disable_all_items()

        if self.message:
            try:
                await self.message.edit(view=self, content=f"{self.message.content or ''}\n\n**[Timed Out]**")
            except discord.NotFound:
                # Message might have been deleted
                pass
            except discord.HTTPException as e:
                self.log.warning("Failed to update message on timeout: %s", e)

    def disable_all_items(self) -> None:
        """Disable all interactive items in the view."""
        for item in self.children:
            if hasattr(item, "disabled"):
                cast("ui.Button | ui.Select", item).disabled = True

    async def reply(  # noqa: PLR0913
        self,
        interaction: discord.Interaction,
        content: str | None = None,
        embed: discord.Embed = MISSING,
        embeds: list[discord.Embed] = MISSING,
        file: discord.File = MISSING,
        files: list[discord.File] = MISSING,
        ephemeral: bool = False,
        allowed_mentions: discord.AllowedMentions = MISSING,
    ) -> None:
        """Send a message with this view and automatically track the message."""
        await interaction.response.send_message(
            content=content,
            embed=embed,
            embeds=embeds,
            file=file,
            files=files,
            ephemeral=ephemeral,
            allowed_mentions=allowed_mentions,
            view=self,
        )
        self.message = await interaction.original_response()


class ModalLauncherView[T: BaseModel](BaseView):
    """Generic view with a configurable button that launches a ModelModal.

    This allows any cog to launch a modal with a customizable button appearance.
    """

    def __init__(  # noqa: PLR0913
        self,
        schema_cls: type[T],
        callback: Callable[[discord.Interaction, T], Any],
        modal_title: str,
        *,
        button_label: str = "Open Form",
        button_emoji: str | None = None,
        button_style: discord.ButtonStyle = discord.ButtonStyle.primary,
        timeout: float | None = 300,
    ) -> None:
        """Initialize the ModalLauncherView.

        Args:
            schema_cls: Pydantic model class for the modal
            callback: Function to call when modal is submitted
            modal_title: Title to display on the modal
            button_label: Text label for the button
            button_emoji: Optional emoji for the button
            button_style: Discord button style (primary, secondary, success, danger)
            timeout: View timeout in seconds
        """
        super().__init__(timeout=timeout)
        self.schema_cls = schema_cls
        self.callback = callback
        self.modal_title = modal_title

        # Create and add the button dynamically
        button = ui.Button(
            label=button_label,
            emoji=button_emoji,
            style=button_style,
        )

        button.callback = self._button_callback  # type: ignore[method-assign]
        self.add_item(button)

    async def _button_callback(self, interaction: discord.Interaction) -> None:
        """Handle button click to open the modal."""
        modal = ModelModal(
            model_cls=self.schema_cls,
            callback=self.callback,
            title=self.modal_title,
        )
        await interaction.response.send_modal(modal)
