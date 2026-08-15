import nextcord
from nextcord import ui
from datetime import datetime, timezone

from src.database import databaseManager
from src.utils.mojang import getuserid
from src.utils.loadConfig import (
    messages, listGamemodes,
    listHighTiers, highTicketCategoryName, roleNames, get_waitlist_role_name,
    get_cooldown_for_member, get_tier_role_name
)
from src.utils import format


# ── Shared helpers ─────────────────────────────────────────────────────────────

def has_waitlist_role(member: nextcord.Member, gm_key: str) -> bool:
    role_name = get_waitlist_role_name(gm_key)
    return any(r.name == role_name for r in member.roles)


async def get_verified_profile(discord_id: int):
    """Returns (ign, tier, server, uuid) from the DB, or None if never verified."""
    if not await databaseManager.userExists(discord_id):
        return None
    return await databaseManager.getUserTicket(discord_id)  # (username, tier, server, uuid)


async def join_waitlist(member: nextcord.Member, gm_key: str, ign: str, uuid: str, server: str) -> str:
    """Adds the gamemode + generic waitlist roles and records the gamemode on the user's row.
    Returns a channel mention (or #channel-name fallback) for the confirmation message."""
    await databaseManager.addUser(
        discordID=member.id, minecraftUsername=ign, minecraftUUID=uuid,
        tier="none", lastTest=0, server=server, gamemode=gm_key
    )

    role = nextcord.utils.get(member.guild.roles, name=get_waitlist_role_name(gm_key))
    if role:
        await member.add_roles(role)

    generic_role = nextcord.utils.get(member.guild.roles, name=roleNames["waitlist"])
    if generic_role:
        await member.add_roles(generic_role)

    ch = nextcord.utils.get(member.guild.text_channels, name=listGamemodes[gm_key]["queue_channel"])
    return f"<#{ch.id}>" if ch else f"#{listGamemodes[gm_key]['queue_channel']}"


async def leave_waitlist(member: nextcord.Member, gm_key: str):
    """Removes the gamemode's waitlist role, and the generic waitlist role too
    if this was the last gamemode waitlist the member was on."""
    role = nextcord.utils.get(member.guild.roles, name=get_waitlist_role_name(gm_key))
    if role and role in member.roles:
        await member.remove_roles(role)

    remaining_waitlist_names = [get_waitlist_role_name(k) for k in listGamemodes if k != gm_key]
    still_has_other = any(r.name in remaining_waitlist_names for r in member.roles)
    if not still_has_other:
        generic_role = nextcord.utils.get(member.guild.roles, name=roleNames["waitlist"])
        if generic_role and generic_role in member.roles:
            await member.remove_roles(generic_role)


# ── Verify Panel View — posted in the verify channel ───────────────────────────

class VerifyPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="Verify", style=nextcord.ButtonStyle.danger, custom_id="panelVerify", emoji="✅", row=0)
    async def verify_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        modal = VerifyForm()
        await interaction.response.send_modal(modal)


# ── Waitlist Panel View — posted in #request-test ──────────────────────────────

class PanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WaitlistToggleSelect())

    @nextcord.ui.button(label="My Cooldowns", style=nextcord.ButtonStyle.secondary, custom_id="panelMyCooldowns", emoji="🍀", row=2)
    async def my_cooldowns_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        try:
            member = interaction.user
            member_cooldown = get_cooldown_for_member(member)  # minutes
            now_ts = int(datetime.now(timezone.utc).timestamp())

            lines = []
            for gm_key, gm_data in listGamemodes.items():
                row = await databaseManager.getLastTestForGamemode(member.id, gm_key)
                last_test = row[0] if row else 0
                unlock_ts = last_test + (member_cooldown * 60)
                if now_ts >= unlock_ts:
                    lines.append(f"✅ **{gm_data['display']}** - ready now")
                else:
                    lines.append(f"⏳ **{gm_data['display']}** - ready <t:{unlock_ts}:R>")

            days = round(member_cooldown / (60 * 24), 1)
            days_text = str(int(days)) if days == int(days) else str(days)

            embed = nextcord.Embed(
                title="🍀 Your cooldowns",
                description="\n".join(lines),
                color=0x2ecc71
            )
            embed.set_footer(text=f"Your cooldown length: {days_text} days per test")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)

    @nextcord.ui.button(label="High Tier Testing", style=nextcord.ButtonStyle.success, custom_id="panelHighTierTesting", emoji="🏅", row=2)
    async def high_tier_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        try:
            member = interaction.user

            verified_role = nextcord.utils.get(interaction.guild.roles, name="Verified")
            if verified_role and verified_role not in member.roles:
                await interaction.response.send_message(
                    "You must verify your IGN first in the verify channel.", ephemeral=True
                )
                return

            if not await databaseManager.userExists(member.id):
                await interaction.response.send_message(
                    "Please verify first to register your IGN.", ephemeral=True
                )
                return

            if await databaseManager.isRestriced(member.id):
                await interaction.response.send_message("You are currently restricted.", ephemeral=True)
                return

            view = HighTierGamemodeSelectView()
            await interaction.response.send_message(
                "Select the gamemode you want High Tier Testing for:", view=view, ephemeral=True
            )
        except Exception:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)

    @nextcord.ui.button(label="Remove Waitlist", style=nextcord.ButtonStyle.danger, custom_id="panelRemoveWaitlist", emoji="🚫", row=2)
    async def remove_waitlist_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        try:
            member = interaction.user
            held_keys = [gm_key for gm_key in listGamemodes if has_waitlist_role(member, gm_key)]
            if not held_keys:
                await interaction.response.send_message("You are not on any waitlist.", ephemeral=True)
                return

            view = RemoveWaitlistView(held_keys)
            await interaction.response.send_message("Choose a waitlist to leave:", view=view, ephemeral=True)
        except Exception:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)


# ── Waitlist toggle — persistent select in the panel itself ───────────────────
# Picking a gamemode you're NOT on joins that waitlist.
# Picking a gamemode you ARE already on leaves it.

class WaitlistToggleSelect(ui.Select):
    def __init__(self):
        options = [
            nextcord.SelectOption(label=gm_data["display"], value=gm_key, emoji=gm_data.get("emoji"))
            for gm_key, gm_data in listGamemodes.items()
        ]
        super().__init__(
            placeholder="Choose a waitlist…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="panelWaitlistToggleSelect",
            row=1
        )

    async def callback(self, interaction: nextcord.Interaction):
        try:
            member = interaction.user

            verified_role = nextcord.utils.get(interaction.guild.roles, name="Verified")
            if verified_role and verified_role not in member.roles:
                await interaction.response.send_message(
                    "You must verify your IGN first in the verify channel.", ephemeral=True
                )
                return

            if await databaseManager.isRestriced(member.id):
                await interaction.response.send_message("You are currently restricted.", ephemeral=True)
                return

            profile = await get_verified_profile(member.id)
            if profile is None:
                await interaction.response.send_message(
                    "Please verify first to register your IGN.", ephemeral=True
                )
                return
            ign, _tier, server, uuid = profile

            gm_key = self.values[0]
            display = listGamemodes[gm_key]["display"]

            if has_waitlist_role(member, gm_key):
                await leave_waitlist(member, gm_key)
                await interaction.response.send_message(f"❌ Left the waitlist for **{display}**.", ephemeral=True)
            else:
                channel_mention = await join_waitlist(member, gm_key, ign, uuid, server)
                await interaction.response.send_message(
                    f"✅ Joined the waitlist for **{display}**!\nKeep an eye on {channel_mention} for when a queue opens.",
                    ephemeral=True
                )
        except Exception:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)


# ── Remove Waitlist — ephemeral picker showing only gamemodes you're on ────────

class RemoveWaitlistView(ui.View):
    def __init__(self, held_keys):
        super().__init__(timeout=120)
        self.add_item(RemoveWaitlistSelect(held_keys))


class RemoveWaitlistSelect(ui.Select):
    def __init__(self, held_keys):
        options = [
            nextcord.SelectOption(
                label=listGamemodes[k]["display"], value=k, emoji=listGamemodes[k].get("emoji")
            )
            for k in held_keys
        ]
        super().__init__(placeholder="Choose a waitlist to leave…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            gm_key = self.values[0]
            display = listGamemodes[gm_key]["display"]
            await leave_waitlist(interaction.user, gm_key)
            await interaction.response.edit_message(content=f"❌ Left the waitlist for **{display}**.", view=None)
        except Exception:
            await interaction.response.edit_message(content=messages["error"], view=None)


# ── High Tier Testing — pick a gamemode, gated by per-gamemode tier ────────────

class HighTierGamemodeSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(HighTierGamemodeSelect())


class HighTierGamemodeSelect(ui.Select):
    def __init__(self):
        options = [
            nextcord.SelectOption(label=gm_data["display"], value=gm_key, emoji=gm_data.get("emoji"))
            for gm_key, gm_data in listGamemodes.items()
        ]
        super().__init__(placeholder="Choose a gamemode…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            member = interaction.user
            gm_key = self.values[0]
            display = listGamemodes[gm_key]["display"]

            # Check Discord roles directly (not the DB record) — matches whatever
            # tier role the player currently holds for this gamemode.
            role_names_by_tier = {t: get_tier_role_name(gm_key, t) for t in listHighTiers}
            held_role_names = {r.name for r in member.roles}

            gm_tier = next(
                (t for t in listHighTiers if role_names_by_tier[t] in held_role_names),
                None
            )

            if gm_tier is None:
                await interaction.response.edit_message(
                    content=f"❌ You're not allowed to — you need an **HT3 or better** role in **{display}**.",
                    view=None
                )
                return

            cat = nextcord.utils.get(interaction.guild.categories, name=highTicketCategoryName)
            if cat is None:
                await interaction.response.edit_message(
                    content="Bot not set up correctly: high-tier ticket category not found.", view=None
                )
                return

            ticket_ch = await interaction.guild.create_text_channel(name=f"hightest-{member.name}-{gm_key}", category=cat)
            overwrite = nextcord.PermissionOverwrite(view_channel=True, send_messages=True)
            await ticket_ch.set_permissions(member, overwrite=overwrite)

            messageData = await databaseManager.getUserTicket(member.id)
            ticketMessage = format.formathighticketmessage(
                username=messageData[0], tier=gm_tier, uuid=messageData[3], gamemode=display
            )
            await ticket_ch.send(content=f"<@{member.id}>", embed=nextcord.Embed.from_dict(ticketMessage))
            await interaction.response.edit_message(
                content=f"✅ A high-tier ticket for **{display}** has been created: <#{ticket_ch.id}>", view=None
            )
        except Exception:
            await interaction.response.edit_message(content=messages["error"], view=None)


# ── Verify Modal — IGN and server ─────────────────────────────────────────────

class VerifyForm(ui.Modal):
    def __init__(self):
        super().__init__("Verify — Register your IGN")

        self.ign = ui.TextInput(
            label="Minecraft Username",
            placeholder="Enter your in-game name",
            required=True
        )

        self.add_item(self.ign)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            uuid = await getuserid(self.ign.value)
            if uuid == "8667ba71b85a4004af54457a9734eed7":
                await interaction.response.send_message("Minecraft username does not exist.", ephemeral=True)
                return

            # Save to DB with placeholder tier/gamemode (server field removed — no longer collected)
            await databaseManager.addUser(
                discordID=interaction.user.id,
                minecraftUsername=self.ign.value,
                minecraftUUID=uuid,
                tier="none",
                lastTest=0,
                server="N/A",
                gamemode="none"
            )

            # Grant the Verified role
            verified_role = nextcord.utils.get(interaction.guild.roles, name="Verified")
            if verified_role:
                await interaction.user.add_roles(verified_role)

            # Set their server nickname to their IGN
            nick_warning = ""
            try:
                await interaction.user.edit(nick=self.ign.value[:32])
            except nextcord.Forbidden:
                nick_warning = "\n⚠️ Couldn't update your nickname (bot may lack permission or your role is above the bot's)."
            except Exception:
                nick_warning = "\n⚠️ Couldn't update your nickname."

            await interaction.response.send_message(
                f"✅ Verified! IGN set to **{self.ign.value}**.\nHead over to the request-test channel and use the **Choose a waitlist** dropdown to join a gamemode.{nick_warning}",
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)
