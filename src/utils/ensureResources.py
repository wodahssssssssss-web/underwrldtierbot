"""
utils/ensureResources.py
========================
Ensures all Discord roles, categories, and channels required by the bot
exist in the guild.  Any missing resource is created automatically on startup.

Call `await ensure_all(guild)` once inside on_ready before doing anything else.
"""

from __future__ import annotations
import logging
import nextcord

from src.utils.loadConfig import (
    roleNames,
    channelNames,
    ticketCategoryName,
    highTicketCategoryName,
    queueCategoryName,
    listGamemodes,
    listGamemodeKeys,
    tierOrder,
    get_tier_role_name,
    get_waitlist_role_name,
)

log = logging.getLogger(__name__)


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _get_or_create_role(guild: nextcord.Guild, name: str, **kwargs) -> nextcord.Role:
    """Return the role with *name*, creating it (with **kwargs) if absent."""
    role = nextcord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, **kwargs)
        log.info(f"[ensureResources] Created role: '{name}'")
    return role


async def _get_or_create_category(guild: nextcord.Guild, name: str) -> nextcord.CategoryChannel:
    """Return the category with *name*, creating it if absent."""
    cat = nextcord.utils.get(guild.categories, name=name)
    if cat is None:
        cat = await guild.create_category(name=name)
        log.info(f"[ensureResources] Created category: '{name}'")
    return cat


async def _get_or_create_text_channel(
    guild: nextcord.Guild,
    name: str,
    category: nextcord.CategoryChannel | None = None,
) -> nextcord.TextChannel:
    """Return the text channel with *name*, creating it (in *category*) if absent."""
    ch = nextcord.utils.get(guild.text_channels, name=name)
    if ch is None:
        ch = await guild.create_text_channel(name=name, category=category)
        log.info(f"[ensureResources] Created channel: '#{name}'" + (f" in '{category.name}'" if category else ""))
    return ch


# ── Public entry point ─────────────────────────────────────────────────────────

async def ensure_all(guild: nextcord.Guild) -> None:
    """
    Idempotently ensure every role, category, and channel the bot needs exists.
    Safe to call on every startup — existing resources are never modified.
    """
    log.info(f"[ensureResources] Checking resources for guild '{guild.name}' …")

    # ── Global roles ───────────────────────────────────────────────────────────
    await _get_or_create_role(guild, roleNames["tester"],   mentionable=False)
    await _get_or_create_role(guild, roleNames["staff"],    mentionable=False)
    await _get_or_create_role(guild, roleNames["waitlist"], mentionable=True)
    await _get_or_create_role(guild, "Verified", mentionable=False, color=nextcord.Color(0xdd2e44))

    # ── Per-gamemode waitlist roles ────────────────────────────────────────────
    for gm_key in listGamemodeKeys:
        await _get_or_create_role(guild, get_waitlist_role_name(gm_key), mentionable=True)

    # ── Per-gamemode tier roles ────────────────────────────────────────────────
    tier_colors = {"1": nextcord.Color(0xe91e63), "2": nextcord.Color(0xd1862a), "3": nextcord.Color(0xf1c40f), "4": nextcord.Color(0x9b59b6), "5": nextcord.Color(0x2ecc71)}
    for gm_key in listGamemodeKeys:
        for tier in tierOrder:
            tier_num = tier[-1]
            color = tier_colors.get(tier_num, nextcord.Color.default())
            await _get_or_create_role(guild, get_tier_role_name(gm_key, tier), mentionable=False, color=color)

    # ── Queue channels category ────────────────────────────────────────────────
    queue_cat: nextcord.CategoryChannel | None = None
    if queueCategoryName:
        queue_cat = await _get_or_create_category(guild, queueCategoryName)

    # ── Per-gamemode queue channels ────────────────────────────────────────────
    for gm_key, gm_data in listGamemodes.items():
        await _get_or_create_text_channel(guild, gm_data["queue_channel"], category=queue_cat)

    # ── Ticket categories ──────────────────────────────────────────────────────
    await _get_or_create_category(guild, ticketCategoryName)
    await _get_or_create_category(guild, highTicketCategoryName)

    # ── Global channels ────────────────────────────────────────────────────────
    await _get_or_create_text_channel(guild, channelNames["announcements"])
    await _get_or_create_text_channel(guild, channelNames["verify"])
    await _get_or_create_text_channel(guild, channelNames["join_queue"])
    await _get_or_create_text_channel(guild, channelNames["tester_logs"])

    log.info(f"[ensureResources] All resources verified for '{guild.name}'.")
