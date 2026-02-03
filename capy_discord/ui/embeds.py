"""Standard embed factory functions and colors for consistent UI."""

import discord

from capy_discord.exts import tickets


def unmarked_embed(
    title: str,
    description: str | None = None,
    *,
    emoji: str | None = None,
) -> discord.Embed:
    """Create an unmarked status embed.

    Args:
        title: The embed title
        description: Optional description
        emoji: Optional emoji to prepend to title

    Returns:
        A blue embed indicating unmarked status
    """
    full_title = f"{emoji} {title}" if emoji else title
    return discord.Embed(
        title=full_title,
        description=description,
        color=tickets.STATUS_UNMARKED,
    )


def success_embed(
    title: str,
    description: str | None = None,
    *,
    emoji: str | None = None,
) -> discord.Embed:
    """Create a success/acknowledged status embed.

    Args:
        title: The embed title
        description: Optional description
        emoji: Optional emoji to prepend to title

    Returns:
        A green embed indicating success or acknowledgment
    """
    full_title = f"{emoji} {title}" if emoji else title
    return discord.Embed(
        title=full_title,
        description=description,
        color=tickets.STATUS_ACKNOWLEDGED,
    )


def ignored_embed(
    title: str,
    description: str | None = None,
    *,
    emoji: str | None = None,
) -> discord.Embed:
    """Create an ignored status embed.

    Args:
        title: The embed title
        description: Optional description
        emoji: Optional emoji to prepend to title

    Returns:
        A greyple embed indicating ignored status
    """
    full_title = f"{emoji} {title}" if emoji else title
    return discord.Embed(
        title=full_title,
        description=description,
        color=tickets.STATUS_IGNORED,
    )
