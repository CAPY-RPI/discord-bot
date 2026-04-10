import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, Literal

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.ui.embeds import error_embed, info_embed, success_embed
from capy_discord.ui.forms import ModelModal
from capy_discord.ui.views import BaseView

from ._schemas import UserProfileDetailsSchema, UserProfileIdentitySchema, UserProfileSchema
from ._service import (
    InvalidProfileError,
    ProfileExistsError,
    ProfileNotFoundError,
    ProfileService,
)


class ConfirmDeleteView(BaseView):
    """View to confirm profile deletion."""

    def __init__(self) -> None:
        """Initialize the ConfirmDeleteView."""
        super().__init__(timeout=60)
        self.value: bool | None = None

    @ui.button(label="Delete Profile", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Button to confirm profile deletion."""
        self.value = True
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Button to cancel profile deletion."""
        self.value = False
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()


class ProfileLaunchButton(ui.Button["ProfileModalLauncherView"]):
    """Button that opens the next step of the profile editor."""

    @property
    def launcher_view(self) -> "ProfileModalLauncherView":
        """Return the attached launcher view."""
        if self.view is None:
            msg = "ProfileLaunchButton must be attached to a ProfileModalLauncherView before use."
            raise RuntimeError(msg)
        return self.view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Delegate button clicks to the parent view callback."""
        await self.launcher_view.open_modal(interaction)


class ProfileModalLauncherView(BaseView):
    """Launch the multi-step profile editor from a button."""

    def __init__(
        self,
        callback: Callable[[discord.Interaction], Awaitable[None]],
        *,
        button_label: str = "Open Profile Form",
        button_emoji: str | None = None,
        button_style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ) -> None:
        """Initialize the launcher view."""
        super().__init__(timeout=300)
        self._callback = callback
        self.add_item(ProfileLaunchButton(label=button_label, emoji=button_emoji, style=button_style))

    async def open_modal(self, interaction: discord.Interaction) -> None:
        """Open the first profile modal."""
        await self._callback(interaction)


class Profile(commands.Cog):
    """Manage user profiles using a single command with choices."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Profile cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.service = ProfileService(bot, self.log)

    @app_commands.command(name="profile", description="Manage your profile")
    @app_commands.describe(action="The action to perform with your profile")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="create", value="create"),
            app_commands.Choice(name="update", value="update"),
            app_commands.Choice(name="show", value="show"),
            app_commands.Choice(name="delete", value="delete"),
            app_commands.Choice(name="test", value="test"),
        ]
    )
    async def profile(self, interaction: discord.Interaction, action: str) -> None:
        """Handle profile actions based on the selected choice."""
        if action in ["create", "update"]:
            await self.handle_edit_action(interaction, action)
        elif action == "show":
            await self.handle_show_action(interaction)
        elif action == "delete":
            await self.handle_delete_action(interaction)
        elif action == "test":
            await interaction.response.send_message("Profile Cog: **Test Version 2.0**", ephemeral=True)

    async def handle_edit_action(self, interaction: discord.Interaction, action: str) -> None:
        """Logic for creating or updating a profile."""
        try:
            initial_data = self.service.start_edit(interaction.user.id, action)
        except ProfileExistsError:
            await self._send_error(
                interaction,
                "Profile Exists",
                "You already have a profile! Use `/profile action:update` to edit it.",
            )
            return
        except ProfileNotFoundError:
            await self._send_error(
                interaction,
                "No Profile",
                "You don't have a profile yet! Use `/profile action:create` first.",
            )
            return

        self.log.info("Opening profile modal for user %s (%s)", interaction.user, action)
        await self._open_profile_identity_modal(interaction, action, initial_data)

    async def _open_profile_identity_modal(
        self,
        interaction: discord.Interaction,
        action: str,
        initial_data: dict[str, Any] | None,
    ) -> None:
        """Open the first step of the profile editor."""
        modal = ModelModal(
            model_cls=UserProfileIdentitySchema,
            callback=partial(self._handle_profile_identity_submit, action=action),
            title=f"{action.title()} Your Profile (1/2)",
            initial_data=initial_data,
        )
        await interaction.response.send_modal(modal)

    async def _handle_profile_identity_submit(
        self, interaction: discord.Interaction, identity: UserProfileIdentitySchema, action: str
    ) -> None:
        """Persist step-one data and offer a button to continue to step two."""
        profile_data = self.service.merge_identity_step(interaction.user.id, identity)

        view = ProfileModalLauncherView(
            callback=partial(self._open_profile_details_modal, action=action, profile_data=profile_data),
            button_label="Finish Profile",
            button_emoji="➡️",
            button_style=discord.ButtonStyle.success,
        )
        await interaction.response.send_message(
            content="Step 1 of 2 complete. Click below to finish your profile.",
            ephemeral=True,
            view=view,
        )

    async def _open_profile_details_modal(
        self,
        interaction: discord.Interaction,
        action: str,
        profile_data: dict[str, Any],
    ) -> None:
        """Open the second step of the profile editor."""
        modal = ModelModal(
            model_cls=UserProfileDetailsSchema,
            callback=partial(self._handle_profile_details_submit, profile_data=profile_data, action=action),
            title=f"{action.title()} Your Profile (2/2)",
            initial_data=profile_data,
        )
        await interaction.response.send_modal(modal)

    async def _handle_profile_details_submit(
        self,
        interaction: discord.Interaction,
        details: UserProfileDetailsSchema,
        profile_data: dict[str, Any],
        action: Literal["create", "update"],
    ) -> None:
        """Combine both modal steps into a validated profile."""
        try:
            profile, result = self.service.finalize_profile(interaction.user, details, profile_data, action)
        except InvalidProfileError:
            await self._send_error(
                interaction,
                "Profile Validation Failed",
                "Please restart the profile flow and try again.",
            )
            return

        await self._handle_profile_submit(interaction, profile, result)

    async def handle_show_action(self, interaction: discord.Interaction) -> None:
        """Logic for the 'show' choice."""
        try:
            profile = self.service.get_profile(interaction.user.id)
        except ProfileNotFoundError:
            await self._send_error(
                interaction,
                "No Profile",
                "You haven't set up a profile yet! Use `/profile action:create`.",
            )
            return

        embed = self.service.create_profile_embed(interaction.user, profile)
        await interaction.response.send_message(embed=embed)

    async def handle_delete_action(self, interaction: discord.Interaction) -> None:
        """Logic for the 'delete' choice."""
        try:
            self.service.get_profile(interaction.user.id)
        except ProfileNotFoundError:
            await self._send_error(interaction, "No Profile", "You don't have a profile to delete.")
            return

        view = ConfirmDeleteView()
        await view.reply(
            interaction,
            content="⚠️ **Are you sure you want to delete your profile?**\nThis action cannot be undone.",
            ephemeral=True,
        )

        await view.wait()

        if view.value is True:
            self.service.delete_profile(interaction.user)
            embed = success_embed("Profile Deleted", "Your profile has been deleted.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = info_embed("Cancelled", "Profile deletion cancelled.")
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_profile_submit(
        self,
        interaction: discord.Interaction,
        profile: UserProfileSchema,
        result: Literal["created", "updated"],
    ) -> None:
        """Process the valid profile submission."""
        embed = self.service.create_profile_embed(interaction.user, profile)
        if result == "created":
            success = success_embed("Profile Created", "Your profile has been created successfully!")
        else:
            success = success_embed("Profile Updated", "Your profile has been updated successfully!")
        await interaction.response.send_message(embeds=[success, embed], ephemeral=True)

    async def _send_error(self, interaction: discord.Interaction, title: str, message: str) -> None:
        """Send a standard ephemeral error embed."""
        await interaction.response.send_message(embed=error_embed(title, message), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the Profile cog."""
    await bot.add_cog(Profile(bot))
