"""Tests for the embed utility functions."""

import discord

from capy_discord.utils.embeds import (
    error_embed,
    ignored_embed,
    important_embed,
    info_embed,
    success_embed,
    unmarked_embed,
    warning_embed,
)


def test_error_embed():
    """Test the error_embed helper function."""
    title = "Error Title"
    description = "Error Description"
    embed = error_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.red()


def test_success_embed():
    """Test the success_embed helper function."""
    title = "Success Title"
    description = "Success Description"
    embed = success_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.green()


def test_info_embed():
    """Test the info_embed helper function."""
    title = "Info Title"
    description = "Info Description"
    embed = info_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.blue()


def test_warning_embed():
    """Test the warning_embed helper function."""
    title = "Warning Title"
    description = "Warning Description"
    embed = warning_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.yellow()


def test_important_embed():
    """Test the important_embed helper function."""
    title = "Important Title"
    description = "Important Description"
    embed = important_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.gold()


def test_unmarked_embed():
    """Test the unmarked_embed helper function."""
    title = "Unmarked Title"
    description = "Unmarked Description"
    embed = unmarked_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.light_grey()


def test_ignored_embed():
    """Test the ignored_embed helper function."""
    title = "Ignored Title"
    description = "Ignored Description"
    embed = ignored_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.greyple()
