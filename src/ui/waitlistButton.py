import nextcord
from nextcord import ui

from src.database import databaseManager
from src.utils.mojang import getuserid
from src.utils.loadConfig import (
    messages, listGamemodes,
    listHighTiers, highTicketCategoryName, roleNames, get_waitlist_role_name
)
from src.utils import format


# ── Panel View — posted in #request-test ──────────────────────────────────────

class PanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="Verify", style=nextcord.ButtonStyle.danger, custom_id="panelVerify", emoji="✅", row=0)
    async def verify_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        modal = VerifyForm()
        await interaction.response.send_modal(modal)

    @nextcord.ui.button(label="Request Test", style=nextcord.ButtonStyle.danger, custom_id="panelRequestTest", emoji="🎮", row=0)
    async def request_test_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Must be verified first
        verified_role = nextcord.utils.get(interaction.guild.roles, name="Verified")
        if verified_role and verified_role not in interaction.user.roles:
            await interaction.response.send_message(
                "You must verify your IGN first by clicking **Verify**.", ephemeral=True
            )
            return

        exists = await databaseManager.userExists(interaction.user.id)
        if exists:
            if await databaseManager.isRestriced(interaction.user.id):
                await interaction.response.send_message("You are currently restricted.", ephemeral=True)
                return

            current_tier = (await databaseManager.getTier(interaction.user.id))[0]
            if current_tier in listHighTiers:
                cat = nextcord.utils.get(interaction.guild.categories, name=highTicketCategoryName)
                if cat is None:
                    await interaction.response.send_message(
                        "Bot not set up correctly: high-tier ticket category not found.", ephemeral=True
                    )
                    return

                ticket_ch = await interaction.guild.create_text_channel(
                    name=f"hightest-{interaction.user.name}", category=cat
                )
                overwrite = nextcord.PermissionOverwrite(view_channel=True, send_messages=True)
                await ticket_ch.set_permissions(interaction.user, overwrite=overwrite)

                messageData = await databaseManager.getUserTicket(interaction.user.id)
                ticketMessage = format.formathighticketmessage(
                    username=messageData[0], tier=messageData[1], uuid=messageData[3]
                )
                await ticket_ch.send(
                    content=f"<@{interaction.user.id}>",
                    embed=nextcord.Embed.from_dict(ticketMessage)
                )
                await interaction.response.send_message(
                    f"A high-tier ticket has been created: <#{ticket_ch.id}>", ephemeral=True
                )
                return

        # Open gamemode selector directly (they already verified IGN)
        if exists:
            view = GamemodeSelectView(ign=None, uuid=None, server=None, from_db=True, discord_id=interaction.user.id)
            await interaction.response.send_message(
                "**Select the gamemode(s) you want to be tested in:**",
                view=view,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Please click **Verify** first to register your IGN and server.", ephemeral=True
            )


# ── Verify Modal — IGN and server ─────────────────────────────────────────────

class VerifyForm(ui.Modal):
    def __init__(self):
        super().__init__("Verify — Register your IGN & Server")

        self.ign = ui.TextInput(
            label="Minecraft Username",
            placeholder="Enter your in-game name",
            required=True
        )
        self.server = ui.TextInput(
            label="Preferred Test Server",
            placeholder="e.g. Hypixel, PotPvP, etc.",
            style=nextcord.TextInputStyle.short,
            required=True
        )

        self.add_item(self.ign)
        self.add_item(self.server)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            uuid = await getuserid(self.ign.value)
            if uuid == "8667ba71b85a4004af54457a9734eed7":
                await interaction.response.send_message("Minecraft username does not exist.", ephemeral=True)
                return

            # Save to DB with placeholder tier/gamemode
            await databaseManager.addUser(
                discordID=interaction.user.id,
                minecraftUsername=self.ign.value,
                minecraftUUID=uuid,
                tier="none",
                lastTest=0,
                server=self.server.value,
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
                f"✅ Verified! IGN set to **{self.ign.value}** on **{self.server.value}**.\nYou can now click **Request Test** to join a gamemode waitlist.{nick_warning}",
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)


# ── Gamemode Select — pick gamemode(s) ────────────────────────────────────────

class GamemodeSelectView(ui.View):
    def __init__(self, ign, uuid, server, from_db=False, discord_id=None):
        super().__init__(timeout=120)
        self.add_item(GamemodeSelect(ign=ign, uuid=uuid, server=server, from_db=from_db, discord_id=discord_id))


class GamemodeSelect(ui.Select):
    def __init__(self, ign, uuid, server, from_db=False, discord_id=None):
        self.ign = ign
        self.uuid = uuid
        self.server = server
        self.from_db = from_db
        self.discord_id = discord_id

        options = [
            nextcord.SelectOption(
                label=gm_data["display"],
                value=gm_key,
                emoji=gm_data.get("emoji")
            )
            for gm_key, gm_data in listGamemodes.items()
        ]

        super().__init__(
            placeholder="Choose your gamemode(s)…",
            min_values=1,
            max_values=len(options),
            options=options,
            custom_id="gamemodeSelect"
        )

    async def callback(self, interaction: nextcord.Interaction):
        try:
            selected_keys = self.values

            if self.from_db:
                # Pull IGN/server/uuid from DB
                info = await databaseManager.getResultInfo(interaction.user.id)
                ign = info[0]
                from src.utils.mojang import getuserid as _getuuid
                uuid = await _getuuid(username=ign)
                server_info = await databaseManager.getUserTicket(interaction.user.id)
                server = server_info[2] if server_info else "Unknown"
            else:
                ign = self.ign
                uuid = self.uuid
                server = self.server

            primary_key = selected_keys[0]

            await databaseManager.addUser(
                discordID=interaction.user.id,
                minecraftUsername=ign,
                minecraftUUID=uuid,
                tier="none",
                lastTest=0,
                server=server,
                gamemode=primary_key
            )

            # Remove old waitlist roles
            all_waitlist_names = (
                [get_waitlist_role_name(k) for k in listGamemodes]
                + [roleNames["waitlist"]]
            )
            roles_to_remove = [r for r in interaction.user.roles if r.name in all_waitlist_names]
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)

            # Add waitlist role for each selected gamemode
            added_roles = []
            for gm_key in selected_keys:
                role = nextcord.utils.get(interaction.guild.roles, name=get_waitlist_role_name(gm_key))
                if role:
                    await interaction.user.add_roles(role)
                    added_roles.append(listGamemodes[gm_key]["display"])

            # Add generic waitlist role
            generic_role = nextcord.utils.get(interaction.guild.roles, name=roleNames["waitlist"])
            if generic_role:
                await interaction.user.add_roles(generic_role)

            # Build channel mentions
            channel_mentions = []
            for gm_key in selected_keys:
                ch = nextcord.utils.get(
                    interaction.guild.text_channels,
                    name=listGamemodes[gm_key]["queue_channel"]
                )
                if ch:
                    channel_mentions.append(f"<#{ch.id}>")
                else:
                    channel_mentions.append(f"#{listGamemodes[gm_key]['queue_channel']}")

            gamemode_list = ", ".join(f"**{listGamemodes[k]['display']}**" for k in selected_keys)
            channels_list = ", ".join(channel_mentions)

            await interaction.response.edit_message(
                content=f"✅ You've been added to the waitlist for {gamemode_list}!\nKeep an eye on {channels_list} for when a queue opens.",
                view=None
            )

        except Exception as e:
            await interaction.response.edit_message(content=messages["error"], view=None)
