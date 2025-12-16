# typing.Any removed to avoid using dynamic typing in metaclass __call__

from discord.ext.commands import AutoShardedBot

from capy_discord.utils import EXTENSIONS


class Bot(AutoShardedBot):
    """Bot class for Capy Discord."""

    async def setup_hook(self) -> None:
        """Run before the bot starts."""
        await self.load_extensions()

    async def load_extensions(self) -> None:
        """Load all enabled extensions."""
        for extension in EXTENSIONS:
            await self.load_extension(extension)

    pass
