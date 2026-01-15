import logging

from discord.ext.commands import AutoShardedBot

from capy_discord.utils import EXTENSIONS


class Bot(AutoShardedBot):
    """Bot class for Capy Discord."""

    async def setup_hook(self) -> None:
        """Run before the bot starts."""
        self.log = logging.getLogger(__name__)
        await self.load_extensions()

    async def load_extensions(self) -> None:
        """Load all enabled extensions."""
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                self.log.info("Loaded extension: %s", extension)
            except Exception:
                self.log.exception("Failed to load extension: %s", extension)
