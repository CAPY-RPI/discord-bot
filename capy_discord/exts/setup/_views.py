"""Views for onboarding interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

from capy_discord.ui.views import BaseView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class VerifyView(BaseView):
    """Button view that lets a joining member accept server rules."""

    def __init__(
        self,
        *,
        attempt_id: int,
        target_user_id: int,
        on_accept: Callable[[discord.Interaction, int, int], Awaitable[bool]],
        on_timeout_callback: Callable[[int], Awaitable[None]],
        timeout: float = 1800,
    ) -> None:
        """Initialize a verification view tied to one target user."""
        super().__init__(timeout=timeout)
        self.attempt_id = attempt_id
        self.target_user_id = target_user_id
        self._on_accept = on_accept
        self._on_timeout_callback = on_timeout_callback

    @ui.button(label="Accept Rules", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Handle acceptance for the target user."""
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message(
                "This verification button is only for the member being onboarded.",
                ephemeral=True,
            )
            return

        completed = await self._on_accept(interaction, self.target_user_id, self.attempt_id)
        if completed:
            self.disable_all_items()
            if self.message:
                await self.message.edit(view=self)
            self.stop()

    async def on_timeout(self) -> None:
        """Mark state timeout and disable all controls when view expires."""
        await self._on_timeout_callback(self.target_user_id)
        await super().on_timeout()
