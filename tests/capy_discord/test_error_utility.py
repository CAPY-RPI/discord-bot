import discord

from capy_discord.ui.embeds import error_embed


def test_error_embed_defaults():
    """Test error_embed with default values."""
    description = "Something went wrong"
    embed = error_embed(description=description)

    assert embed.title == "❌ Error"
    assert embed.description == description
    assert embed.color == discord.Color.red()


def test_error_embed_custom_title():
    """Test error_embed with a custom title."""
    title = "Oops!"
    description = "Something went wrong"
    embed = error_embed(title=title, description=description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.red()
