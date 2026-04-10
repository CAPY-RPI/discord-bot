import logging
from collections.abc import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.ui.embeds import error_embed, success_embed
from capy_discord.ui.forms import ModelModal

from ._schemas import WhenIsGoodPollSchema
from ._service import AvailabilityPoll, WhenIsGoodService
from ._views import AvailabilityVoteView, PollPickerView


class WhenIsGood(commands.Cog):
    """Manage simple availability polls."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the WhenIsGood cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.service = WhenIsGoodService()

    @app_commands.command(name="whenisgood", description="Create and manage availability polls")
    @app_commands.describe(
        action="The availability action to perform",
        poll_id="Optional poll ID to vote on or view results for",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="create", value="create"),
            app_commands.Choice(name="vote", value="vote"),
            app_commands.Choice(name="results", value="results"),
        ]
    )
    async def whenisgood(self, interaction: discord.Interaction, action: str, poll_id: str | None = None) -> None:
        """Handle availability poll actions."""
        if action == "create":
            await self.handle_create_action(interaction)
        elif action == "vote":
            await self.handle_vote_action(interaction, poll_id)
        elif action == "results":
            await self.handle_results_action(interaction, poll_id)

    async def handle_create_action(self, interaction: discord.Interaction) -> None:
        """Open the poll creation modal."""
        if interaction.guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Server", "Availability polls must be created in a server."),
                ephemeral=True,
            )
            return

        modal = ModelModal(
            model_cls=WhenIsGoodPollSchema,
            callback=self._handle_create_submit,
            title="Create Availability Poll",
        )
        await interaction.response.send_modal(modal)

    async def handle_vote_action(self, interaction: discord.Interaction, poll_id: str | None) -> None:
        """Open a selected poll for voting."""
        if interaction.guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Server", "Availability polls must be voted on in a server."),
                ephemeral=True,
            )
            return

        await self._handle_poll_action(
            interaction,
            poll_id=poll_id,
            on_selected=self._open_vote_view,
            empty_message="Create a poll first with `/whenisgood action:create`.",
            selection_prompt="Select which poll you want to vote on:",
        )

    async def handle_results_action(self, interaction: discord.Interaction, poll_id: str | None) -> None:
        """Show results for a selected poll."""
        if interaction.guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Server", "Availability results can only be shown in a server."),
                ephemeral=True,
            )
            return

        await self._handle_poll_action(
            interaction,
            poll_id=poll_id,
            on_selected=self._show_results,
            empty_message="Create a poll first with `/whenisgood action:create`.",
            selection_prompt="Select which poll results you want to view:",
        )

    async def _handle_create_submit(self, interaction: discord.Interaction, poll_data: WhenIsGoodPollSchema) -> None:
        """Create a poll from modal data and show the initial summary."""
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("No Server", "Availability polls must be created in a server."),
                ephemeral=True,
            )
            return

        slots = [line.strip() for line in poll_data.slots.splitlines() if line.strip()]
        poll = self.service.create_poll(
            guild_id=guild_id,
            creator_id=interaction.user.id,
            title=poll_data.title,
            description=poll_data.description,
            slots=slots,
        )
        self.log.info("Created availability poll %s in guild %s", poll.poll_id, guild_id)

        await interaction.response.send_message(
            embeds=[
                success_embed(
                    "Availability Poll Created",
                    f"Your poll is ready. Poll ID: `{poll.poll_id}`. Ask people to run "
                    "`/whenisgood action:vote` to respond.",
                ),
                self.service.build_poll_embed(poll),
            ],
            ephemeral=True,
        )

    async def _handle_poll_action(
        self,
        interaction: discord.Interaction,
        *,
        poll_id: str | None,
        on_selected: Callable[[discord.Interaction, AvailabilityPoll], Awaitable[None]] | None = None,
        empty_message: str,
        selection_prompt: str,
    ) -> None:
        """Resolve a poll by id or let the user pick one when multiple exist."""
        guild_id = interaction.guild_id
        if guild_id is None:
            return

        callback = on_selected or self._show_results

        if poll_id:
            poll = self.service.get_guild_poll(guild_id, poll_id)
            if poll is None:
                await interaction.response.send_message(
                    embed=error_embed("Poll Not Found", f"Could not find poll `{poll_id}` in this server."),
                    ephemeral=True,
                )
                return
            await callback(interaction, poll)
            return

        polls = self.service.list_polls_for_guild(guild_id)
        if not polls:
            await interaction.response.send_message(
                embed=error_embed("No Poll Found", empty_message),
                ephemeral=True,
            )
            return

        if len(polls) == 1:
            await callback(interaction, polls[0])
            return

        await interaction.response.defer(ephemeral=True)
        picker = PollPickerView(polls, callback)
        await interaction.followup.send(content=selection_prompt, view=picker, ephemeral=True)

    async def _open_vote_view(self, interaction: discord.Interaction, poll: AvailabilityPoll) -> None:
        """Open the voting view for a specific poll."""
        self.log.info("Opening availability poll %s for user %s", poll.poll_id, interaction.user)
        view = AvailabilityVoteView(poll, self.service)
        await interaction.response.send_message(
            embeds=[self.service.build_poll_embed(poll)],
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def _show_results(self, interaction: discord.Interaction, poll: AvailabilityPoll) -> None:
        """Show results for a specific poll."""
        await interaction.response.send_message(
            embed=self.service.build_results_embed(poll),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Register the WhenIsGood cog."""
    await bot.add_cog(WhenIsGood(bot))
