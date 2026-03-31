import logging
from collections.abc import Callable
from functools import partial
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands
from pydantic import ValidationError

from capy_discord.ui.embeds import error_embed, info_embed, success_embed
from capy_discord.ui.forms import ModelModal
from capy_discord.ui.views import BaseView

from ._profiles import create_profile_embed, get_profile_store
from ._schemas import UserProfileDetailsSchema, UserProfileIdentitySchema, UserProfileSchema


class ConfirmDeleteView(BaseView):
    """View to confirm profile deletion."""

    def __init__(self) -> None:
        """Initialize the delete confirmation view."""
        super().__init__(timeout=60)
        self.value = None

    @ui.button(label="Delete Profile", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Confirm deletion and stop the view."""
        self.value = True
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        """Cancel deletion and stop the view."""
        self.value = False
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()


class ProfileModalLauncherView(BaseView):
    """Launch the multi-step profile editor from a button."""

    def __init__(
        self,
        callback: Callable[[discord.Interaction], Any],
        *,
        button_label: str = "Open Profile Form",
        button_emoji: str | None = None,
        button_style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ) -> None:
        """Initialize the launcher view for the second profile step."""
        super().__init__(timeout=300)
        self._callback = callback
        self.add_item(ui.Button(label=button_label, emoji=button_emoji, style=button_style))
        self.children[0].callback = self._button_callback  # type: ignore[method-assign]

    async def _button_callback(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction)


class Profile(commands.Cog):
    """Manage user profiles using a single command with choices."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the profile cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.profiles = get_profile_store(bot)

    @app_commands.command(name="profile", description="Manage your profile")
    @app_commands.describe(action="The action to perform with your profile")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="create", value="create"),
            app_commands.Choice(name="update", value="update"),
            app_commands.Choice(name="show", value="show"),
            app_commands.Choice(name="delete", value="delete"),
        ]
    )
    async def profile(self, interaction: discord.Interaction, action: str) -> None:
        """Dispatch profile actions for the invoking user."""
        if action in ["create", "update"]:
            await self.handle_edit_action(interaction, action)
        elif action == "show":
            await self.handle_show_action(interaction)
        elif action == "delete":
            await self.handle_delete_action(interaction)

    async def handle_edit_action(self, interaction: discord.Interaction, action: str) -> None:
        """Start the create or update flow for a profile."""
        user_id = interaction.user.id
        current_profile = self.profiles.get(user_id)

        if action == "create" and current_profile:
            embed = error_embed(
                "Profile Exists", "You already have a profile! Use `/profile action:update` to edit it."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if action == "update" and not current_profile:
            embed = error_embed("No Profile", "You don't have a profile yet! Use `/profile action:create` first.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        initial_data = current_profile.model_dump() if current_profile else None

        self.log.info("Opening profile modal for user %s (%s)", interaction.user, action)
        await self._open_profile_identity_modal(interaction, action, initial_data)

    async def _open_profile_identity_modal(
        self,
        interaction: discord.Interaction,
        action: str,
        initial_data: dict[str, Any] | None,
    ) -> None:
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
        current_profile = self.profiles.get(interaction.user.id)
        profile_data = current_profile.model_dump() if current_profile else {}
        profile_data.update(identity.model_dump())

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
        modal = ModelModal(
            model_cls=UserProfileDetailsSchema,
            callback=partial(self._handle_profile_details_submit, profile_data=profile_data),
            title=f"{action.title()} Your Profile (2/2)",
            initial_data=profile_data,
        )
        await interaction.response.send_modal(modal)

    async def _handle_profile_details_submit(
        self,
        interaction: discord.Interaction,
        details: UserProfileDetailsSchema,
        profile_data: dict[str, Any],
    ) -> None:
        combined_data = {**profile_data, **details.model_dump()}

        try:
            profile = UserProfileSchema(**combined_data)
        except ValidationError as error:
            self.log.warning("Full profile validation failed for user %s: %s", interaction.user, error)
            embed = error_embed("Profile Validation Failed", "Please restart the profile flow and try again.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await self._handle_profile_submit(interaction, profile)

    async def handle_show_action(self, interaction: discord.Interaction) -> None:
        """Display the invoking user's profile."""
        profile = self.profiles.get(interaction.user.id)

        if not profile:
            embed = error_embed("No Profile", "You haven't set up a profile yet! Use `/profile action:create`.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = create_profile_embed(interaction.user, profile)
        await interaction.response.send_message(embed=embed)

    async def handle_delete_action(self, interaction: discord.Interaction) -> None:
        """Prompt for and process profile deletion."""
        profile = self.profiles.get(interaction.user.id)

        if not profile:
            embed = error_embed("No Profile", "You don't have a profile to delete.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = ConfirmDeleteView()
        await view.reply(
            interaction,
            content="⚠️ **Are you sure you want to delete your profile?**\nThis action cannot be undone.",
            ephemeral=True,
        )

        await view.wait()

        if view.value is True:
            del self.profiles[interaction.user.id]
            self.log.info("Deleted profile for user %s", interaction.user)
            embed = success_embed("Profile Deleted", "Your profile has been deleted.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = info_embed("Cancelled", "Profile deletion cancelled.")
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_profile_submit(self, interaction: discord.Interaction, profile: UserProfileSchema) -> None:
        self.profiles[interaction.user.id] = profile

        self.log.info("Updated profile for user %s", interaction.user)

        embed = create_profile_embed(interaction.user, profile)
        success = success_embed("Profile Updated", "Your profile has been updated successfully!")
        await interaction.response.send_message(embeds=[success, embed], ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Register the profile cog."""
    await bot.add_cog(Profile(bot))
