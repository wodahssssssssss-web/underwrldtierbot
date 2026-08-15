"""
DB Sync plugin — Website → Database.

Pulls the site's data.json (via GitHub) and updates the local bot database's
per-gamemode tiers to match, for every player whose Minecraft username we
recognize (i.e. they've verified with the bot at some point).

This is a one-way sync: the website is the source of truth here, and nothing
in this module writes back to GitHub. Cooldown timestamps (lastTest) are
never touched for players who already have a row — only the tier value
updates — since the website has no cooldown-timing data to give us.

Runs on a schedule from main.py (see options.db_sync_interval_hours in
config.yml).
"""

import logging

from src.utils import github
from src.database import databaseManager


async def sync_from_website() -> dict:
    """
    Pulls data.json and updates local DB tiers to match.
    Returns a summary dict: {"updated": int, "skipped_unknown": int}
    """
    data, _sha = github.fetch_data()
    github.ensure_structure(data)

    all_db_users = await databaseManager.getAllUsers()  # [(discordID, username, uuid), ...]
    # Minecraft usernames aren't case-sensitive for matching purposes here
    username_to_discord = {username.strip().lower(): discord_id for discord_id, username, _uuid in all_db_users}

    updated = 0
    skipped_unknown = 0  # site has a placement for a username we don't recognize (never verified)

    for site_mode in github.MODES:
        gm_key = github.bot_mode_key(site_mode)
        placements_for_mode = data["placements"].get(site_mode, {})

        for tier in github.TIERS:
            for username in placements_for_mode.get(tier, []):
                discord_id = username_to_discord.get(username.strip().lower())
                if discord_id is None:
                    skipped_unknown += 1
                    continue
                await databaseManager.setTierForGamemodeSync(discord_id, gm_key, tier)
                updated += 1

    logging.info(
        f"[dbSync] Website → DB sync complete: {updated} tiers updated, "
        f"{skipped_unknown} placements skipped (unrecognized username)."
    )
    return {"updated": updated, "skipped_unknown": skipped_unknown}
