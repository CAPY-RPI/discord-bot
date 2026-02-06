import discord

import capy_discord
from capy_discord.bot import Bot
from capy_discord.config import settings
from capy_discord.logging import setup_logging


def main() -> None:
    """Main function to run the application."""
    setup_logging(settings.log_level)

    # Global bot instance (DEPRECATED: Use Dependency Injection instead).
    # We assign to _instance so that accessing .instance triggers the deprecation warning in __init__.py
    capy_discord._instance = Bot(command_prefix=[settings.prefix, "!"], intents=discord.Intents.all())
    capy_discord._instance.run(settings.token, log_handler=None)


main()
