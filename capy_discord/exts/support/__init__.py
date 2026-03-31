"""Support domain package."""

import discord

STATUS_UNMARKED = discord.Color.blue()
STATUS_ACKNOWLEDGED = discord.Color.green()
STATUS_IGNORED = discord.Color.greyple()

STATUS_EMOJI = {
    "✅": "Acknowledged",
    "❌": "Ignored",
    "🔄": "Unmarked",
}

REACTION_FOOTER = " ✅ Acknowledge • ❌ Ignore • 🔄 Reset"
