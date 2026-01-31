import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands, ui
from discord.ext import commands

from capy_discord.ui.forms import ModelModal
from capy_discord.ui.views import BaseView
from capy_discord.utils.embeds import error_embed, info_embed, success_embed

from ._schemas import UserProfileSchema


class ConfirmDeleteView(BaseView):
    """View to confirm profile deletion."""

    def __init__(self) -> None:
        """Initialize the ConfirmDeleteView."""
        super().__init__(timeout=60)
        self.value = None

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


class Profile(commands.Cog):
    """Manage user profiles using a single command with choices."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Profile cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        # In-memory storage for demonstration.
        self.profiles: dict[int, UserProfileSchema] = {}

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
        user_id = interaction.user.id

        # [DB CALL]: Fetch profile
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

        # Convert Pydantic model to dict for initial data if it exists
        initial_data = current_profile.model_dump() if current_profile else None

        self.log.info("Opening profile modal for user %s (%s)", interaction.user, action)

        modal = ModelModal(
            model_cls=UserProfileSchema,
            callback=self._handle_profile_submit,
            title=f"{action.title()} Your Profile",
            initial_data=initial_data,
        )
        await interaction.response.send_modal(modal)

    async def handle_show_action(self, interaction: discord.Interaction) -> None:
        """Logic for the 'show' choice."""
        profile = self.profiles.get(interaction.user.id)

        if not profile:
            embed = error_embed("No Profile", "You haven't set up a profile yet! Use `/profile action:create`.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = self._create_profile_embed(interaction.user, profile)
        await interaction.response.send_message(embed=embed)

    async def handle_delete_action(self, interaction: discord.Interaction) -> None:
        """Logic for the 'delete' choice."""
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
            # [DB CALL]: Delete profile
            del self.profiles[interaction.user.id]
            self.log.info("Deleted profile for user %s", interaction.user)
            embed = success_embed("Profile Deleted", "Your profile has been deleted.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = info_embed("Cancelled", "Profile deletion cancelled.")
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_profile_submit(self, interaction: discord.Interaction, profile: UserProfileSchema) -> None:
        """Process the valid profile submission."""
        # [DB CALL]: Save profile
        self.profiles[interaction.user.id] = profile

        self.log.info("Updated profile for user %s", interaction.user)

        embed = self._create_profile_embed(interaction.user, profile)
        success = success_embed("Profile Updated", "Your profile has been updated successfully!")
        await interaction.response.send_message(embeds=[success, embed], ephemeral=True)

    def _create_profile_embed(self, user: discord.User | discord.Member, profile: UserProfileSchema) -> discord.Embed:
        """Helper to build the profile display embed."""
        embed = discord.Embed(title=f"{user.display_name}'s Profile")
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="Name", value=profile.preferred_name, inline=True)
        embed.add_field(name="Major", value=profile.major, inline=True)
        embed.add_field(name="Grad Year", value=str(profile.graduation_year), inline=True)
        embed.add_field(name="Email", value=profile.school_email, inline=True)

        # Only show last 4 of ID for privacy in the embed
        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")
        embed.set_footer(text=f"Student ID: *****{profile.student_id[-4:]} • Last updated: {now}")
        return embed


async def setup(bot: commands.Bot) -> None:
    """Set up the Profile cog."""
    await bot.add_cog(Profile(bot))
