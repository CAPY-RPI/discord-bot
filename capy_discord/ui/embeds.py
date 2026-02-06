"""Standard embed utilities for consistent message styling."""

import discord

STATUS_ERROR = discord.Color.red()
STATUS_SUCCESS = discord.Color.green()
STATUS_INFO = discord.Color.blue()
STATUS_WARNING = discord.Color.yellow()
STATUS_IMPORTANT = discord.Color.gold()
STATUS_UNMARKED = discord.Color.light_grey()
STATUS_IGNORED = discord.Color.greyple()


def error_embed(title: str = "❌ Error", description: str = "") -> discord.Embed:
    """Create an error status embed.

    Args:
        title: The title of the embed. Defaults to "❌ Error".
        description: The description of the embed.

    Returns:
        discord.Embed: The created embed.
    """
    return discord.Embed(title=title, description=description, color=STATUS_ERROR)


def success_embed(title: str, description: str) -> discord.Embed:
    """Create a success status embed.

    Args:
        title: The title of the embed.
        description: The description of the embed.

    Returns:
        discord.Embed: The created embed.
    """
    return discord.Embed(title=title, description=description, color=STATUS_SUCCESS)


def info_embed(title: str, description: str) -> discord.Embed:
    """Create an info status embed.

    Args:
        title: The title of the embed.
        description: The description of the embed.

    Returns:
        discord.Embed: The created embed.
    """
    return discord.Embed(title=title, description=description, color=STATUS_INFO)


def warning_embed(title: str, description: str) -> discord.Embed:
    """Create a warning status embed.

    Args:
        title: The title of the embed.
        description: The description of the embed.

    Returns:
        discord.Embed: The created embed.
    """
    return discord.Embed(title=title, description=description, color=STATUS_WARNING)


def important_embed(title: str, description: str) -> discord.Embed:
    """Create an important status embed.

    Args:
        title: The title of the embed.
        description: The description of the embed.

    Returns:
        discord.Embed: The created embed.
    """
    return discord.Embed(title=title, description=description, color=STATUS_IMPORTANT)


def unmarked_embed(title: str, description: str) -> discord.Embed:
    """Create an unmarked status embed.

    Args:
        title: The title of the embed.
        description: The description of the embed.

    Returns:
        discord.Embed: The created embed.
    """
    return discord.Embed(title=title, description=description, color=STATUS_UNMARKED)


def ignored_embed(title: str, description: str) -> discord.Embed:
    """Create an ignored status embed.

    Args:
        title: The title of the embed.
        description: The description of the embed.

    Returns:
        discord.Embed: The created embed.
    """
    return discord.Embed(title=title, description=description, color=STATUS_IGNORED)
