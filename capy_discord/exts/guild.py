import logging

import discord
from discord.ext import commands


class Guild(commands.Cog):
    """Handle guild-related events and management."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Guild cog."""
        self.bot = bot
        self.log = logging.getLogger(__name__)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Listener that runs when the bot joins a new guild."""
        self.log.info("Joined new guild: %s (ID: %s)", guild.name, guild.id)

        # [DB CALL]: Check if guild.id exists in the 'guilds' table.
        # existing_guild = await db.fetch_guild(guild.id)

        # if not existing_guild:
        # [DB CALL]: Insert the new guild into the database.
        # await db.create_guild(
        #     id=guild.id,
        #     name=guild.name,
        #     owner_id=guild.owner_id,
        #     created_at=guild.created_at
        # )
        # self.log.info("Registered new guild in database: %s", guild.id)
        # else:
        # self.log.info("Guild %s already exists in database.", guild.id)


async def setup(bot: commands.Bot) -> None:
    """Set up the Guild cog."""
    await bot.add_cog(Guild(bot))
