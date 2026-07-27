import yaml
import logging
import sys

try:
    with open("config/config.yml", "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
except Exception as e:
    logging.exception("Failed to load configuration file:")
    sys.exit("Error: Unable to load config file.")

try:
    # ── Options ────────────────────────────────────────────────────────────────
    maxQueue:    int = config["options"]["queue_limit"]
    maxTester:   int = config["options"]["tester_limit"]
    reloadQueue: int = config["options"]["reload_queue"]
    # Convert days → seconds for cooldown comparisons
    cooldown:        int = config["options"]["cooldown_days"] * 24 * 60  # stored in minutes internally
    boosterCooldown: int = config["options"].get("booster_cooldown_days", config["options"]["cooldown_days"]) * 24 * 60

    # ── Messages ───────────────────────────────────────────────────────────────
    messages: dict = config["messages"]

    # ── Roles (by name) ────────────────────────────────────────────────────────
    roleNames: dict = config["roles"]  # keys: tester, staff, waitlist

    # ── Channels (by name) ────────────────────────────────────────────────────
    channelNames: dict = config["channels"]

    # ── Ticket settings ────────────────────────────────────────────────────────
    ticketCategoryName:   str = config["tickets"]["category"]
    ticketChannelTemplate: str = config["tickets"]["channel_template"]

    # ── High-tier settings ─────────────────────────────────────────────────────
    listHighTiers:         list[str] = config["high_tiers"]
    highTicketCategoryName: str      = config["high_ticket_category"]

    # ── Tier ordering ──────────────────────────────────────────────────────────
    tierOrder: list[str] = config["tier_order"]
    # All valid tier choices (plus "none" for /result)
    listTiers: list[str] = tierOrder + ["none"]

    # ── Gamemodes ──────────────────────────────────────────────────────────────
    listGamemodes:    dict        = config["gamemodes"]
    listGamemodeKeys: list[str]   = list(config["gamemodes"].keys())

    # Slash-command choices: list of display names (nextcord accepts list[str])
    listGamemodesText: list[str] = [gm["display"] for gm in listGamemodes.values()]

    # Quick lookup: display name → key  (for resolving modal/choice input back to key)
    gamemodeDisplayToKey: dict[str, str] = {
        gm["display"]: key for key, gm in listGamemodes.items()
    }

    # All queue channel names (used to guard commands from being run inside them)
    listGamemodeQueueChannelNames: list[str] = [
        gm["queue_channel"] for gm in listGamemodes.values()
    ]

    # All waitlist role names (used to clean up roles on result)
    listGamemodeWaitlistRoleNames: list[str] = [
        gm["role_ping"] for gm in listGamemodes.values()
    ]

    # ── Queue category ─────────────────────────────────────────────────────────
    queueCategoryName: str | None = config.get("queue_category")

    # ── Database ───────────────────────────────────────────────────────────────
    databaseType: str  = config["database"]["type"]
    mysqlInfo:    dict = config["database"]["mysql"]

    # ── Helper functions ───────────────────────────────────────────────────────
    def get_tier_role_name(gamemode_key: str, tier: str) -> str:
        """e.g. get_tier_role_name('axe', 'HT4') → 'Axe & Shield HT4'"""
        display = listGamemodes[gamemode_key]["display"]
        return f"{display} {tier}"

    def get_waitlist_role_name(gamemode_key: str) -> str:
        """e.g. get_waitlist_role_name('sword') → 'Waitlist Sword PvP'"""
        display = listGamemodes[gamemode_key]["display"]
        return f"Waitlist {display}"

    def get_cooldown_for_member(member) -> int:
        """Returns the queue cooldown (in minutes) that applies to this member —
        the shorter booster cooldown if they have the booster role, else the default."""
        if any(r.name == roleNames.get("booster") for r in member.roles):
            return boosterCooldown
        return cooldown

except Exception as e:
    logging.exception("Setting up config failed:")
    sys.exit("Error: Failed to setup config")
