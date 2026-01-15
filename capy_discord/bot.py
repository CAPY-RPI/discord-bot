# typing.Any removed to avoid using dynamic typing in metaclass __call__

import logging

from discord.ext.commands import AutoShardedBot

from capy_discord.utils import EXTENSIONS

log = logging.getLogger(__name__)


class Bot(AutoShardedBot):
    """Bot class for Capy Discord."""

    async def setup_hook(self) -> None:
        """Run before the bot starts."""
        await self.load_extensions()

    async def load_extensions(self) -> None:
        """Load all enabled extensions."""
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                log.info("Loaded extension: %s", extension)
            except Exception:
                log.exception("Failed to load extension: %s", extension)

    pass
