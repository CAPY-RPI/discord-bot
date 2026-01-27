import logging
from collections.abc import Callable
from typing import Any, TypeVar

import discord
from discord import ui


class BaseModal(ui.Modal):
    """A base modal class that implements common functionality.

    This class provides a standard way to handle errors and logging for modals.
    Subclasses should implement their own fields and on_submit logic.
    """

    def __init__(self, *, title: str, timeout: float | None = None) -> None:
        """Initialize the BaseModal."""
        super().__init__(title=title, timeout=timeout)
        self.log = logging.getLogger(__name__)


T = TypeVar("T", bound="CallbackModal")


class CallbackModal[T](BaseModal):
    """A modal that delegates submission logic to a callback function.

    This is useful for decoupling the UI from the business logic.
    """

    def __init__(
        self,
        callback: Callable[[discord.Interaction, T], Any],
        *,
        title: str,
        timeout: float | None = None,
    ) -> None:
        """Initialize the CallbackModal.

        Args:
            callback: A coroutine function to call when the modal is submitted.
                      It should accept (interaction, modal_instance).
            title: The title of the modal.
            timeout: The timeout in seconds.
        """
        super().__init__(title=title, timeout=timeout)
        self.submission_callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Delegate submission to the callback."""
        if self.submission_callback:
            await self.submission_callback(interaction, self)  # type: ignore
