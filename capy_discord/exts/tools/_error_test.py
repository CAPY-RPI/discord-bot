import discord
from discord import app_commands
from discord.ext import commands

from capy_discord.errors import UserFriendlyError


class ErrorTest(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="error-test", description="Trigger various error types for verification")
    @app_commands.choices(
        error_type=[
            app_commands.Choice(name="generic", value="generic"),
            app_commands.Choice(name="user-friendly", value="user-friendly"),
        ]
    )
    async def error_test(self, _interaction: discord.Interaction, error_type: str) -> None:
        if error_type == "generic":
            raise ValueError("Generic error")  # noqa: TRY003
        if error_type == "user-friendly":
            raise UserFriendlyError("Log", "User message")

    @commands.command(name="error-test")
    async def error_test_command(self, _ctx: commands.Context) -> None:
        raise RuntimeError("Test Exception")  # noqa: TRY003


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ErrorTest(bot))
