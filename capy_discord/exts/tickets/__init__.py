"""Ticket submission system for feedback, bug reports, and feature requests."""

import discord

# Standard colors for different ticket status types
STATUS_UNMARKED = discord.Color.blue()
STATUS_ACKNOWLEDGED = discord.Color.green()
STATUS_IGNORED = discord.Color.greyple()

# Status emoji mappings for ticket reactions
STATUS_EMOJI = {
    "✅": "Acknowledged",
    "❌": "Ignored",
    "🔄": "Unmarked",
}

# Reaction footer text for ticket embeds
REACTION_FOOTER = " ✅ Acknowledge • ❌ Ignore • 🔄 Reset"
