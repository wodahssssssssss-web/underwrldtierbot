"""
GitHub-backed data.json helpers.

Reads/writes the website's data.json (placements + playerMeta) directly on
GitHub, the same way the old standalone tier bot did. Used by:
  - the /tier admin command group (manual placements/region/tester/staff edits)
  - /results (auto-pushes the ticket outcome straight to the site)

REQUIRED ENV VARS (bot/.env or project .env):
  GITHUB_TOKEN      — GitHub personal access token with repo contents write access
  GITHUB_REPO       — e.g. "username/underwrldtiers"
  GITHUB_FILE_PATH  — defaults to "data.json"
"""

import os
import json
import base64
import logging
import requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO")
GITHUB_FILE  = os.getenv("GITHUB_FILE_PATH", "data.json")

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
GH_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

# Website mode keys (index.html MODE_KEYS_NO_OVERALL) and tier keys (TIER_KEYS)
MODES   = ["vanilla", "uhc", "pot", "nethop", "smp", "sword", "axe", "mace"]
TIERS   = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5",
           "RHT1", "RLT1", "RHT2", "RLT2"]
REGIONS = ["NA", "EU", "AU", "AS"]

# Ticket-bot gamemode keys (config.yml) that don't match the website's key 1:1
GM_KEY_TO_SITE = {
    "netherite": "nethop",
    "crystal": "vanilla",
}


def site_mode_key(gm_key: str) -> str:
    """Map a ticket-bot gamemode key (config.yml) to the website's mode key."""
    return GM_KEY_TO_SITE.get(gm_key, gm_key)


def fetch_data():
    """Fetch data.json from GitHub. Returns (data_dict, sha_string)."""
    r = requests.get(GITHUB_API, headers=GH_HEADERS)
    r.raise_for_status()
    info = r.json()
    content = base64.b64decode(info["content"]).decode()
    return json.loads(content), info["sha"]


def push_data(data: dict, sha: str, message: str):
    """Push updated data.json back to GitHub."""
    encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload = {"message": message, "content": encoded, "sha": sha}
    r = requests.put(GITHUB_API, headers=GH_HEADERS, json=payload)
    r.raise_for_status()


def ensure_structure(data: dict):
    """Make sure all modes/tiers exist in the data before reading/writing."""
    data.setdefault("placements", {})
    data.setdefault("playerMeta", {})
    for mode in MODES:
        data["placements"].setdefault(mode, {})
        for tier in TIERS:
            data["placements"][mode].setdefault(tier, [])


def set_player_tier(data: dict, site_mode: str, player: str, tier: str | None):
    """
    Place `player` in `tier` for `site_mode`, removing them from every other
    tier in that mode first. Pass tier=None (or "none") to just remove them.
    Also stamps a default AU region the first time a player appears.
    """
    ensure_structure(data)
    if site_mode not in MODES:
        raise ValueError(f"Unknown site mode '{site_mode}'")

    for t in TIERS:
        data["placements"][site_mode][t] = [
            n for n in data["placements"][site_mode][t] if n.lower() != player.lower()
        ]

    if tier and tier.lower() != "none":
        tier = tier.upper().strip()
        if tier not in TIERS:
            raise ValueError(f"Unknown tier '{tier}'")
        data["placements"][site_mode][tier].append(player)

    data["playerMeta"].setdefault(player, {}).setdefault("region", "AU")
