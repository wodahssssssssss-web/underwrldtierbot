"""
Helper to resolve channel/category names to Discord objects.
All channel lookups use names instead of IDs.
"""
import nextcord

def get_channel_by_name(guild: nextcord.Guild, name: str) -> nextcord.TextChannel | None:
    """Find a text channel in the guild by exact name."""
    return nextcord.utils.get(guild.text_channels, name=name)

def get_category_by_name(guild: nextcord.Guild, name: str) -> nextcord.CategoryChannel | None:
    """Find a category in the guild by exact name."""
    return nextcord.utils.get(guild.categories, name=name)
