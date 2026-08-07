import os
import sys
import logging
import time
import asyncio
from datetime import datetime, timezone

import nextcord
from nextcord.ext import commands, tasks
from dotenv import load_dotenv

from src.utils import mojang, format
from src.utils.ensureResources import ensure_all
from src.utils.transcript import post_transcript
from src.utils import github
from src.tierlistQueue import TierlistQueue
from src.ui.waitlistButton import PanelView, VerifyPanelView
from src.ui.enterQueueButton import EnterQueueButton
from src.ui.closeTicketButton import CloseTicketButton
from src.database import databaseManager
from src.utils.loadConfig import *

try:
    os.makedirs("logs", exist_ok=True)
    os.makedirs("storage", exist_ok=True)
except Exception as e:
    print("Unable to create logs/storage directory:", e)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
    handlers=[
        logging.FileHandler(f"logs/logs-{time.time()}.log"),
        logging.StreamHandler()
    ]
)

load_dotenv()

intents = nextcord.Intents.all()
bot = commands.Bot(intents=intents)

try:
    queue = TierlistQueue(maxQueue=maxQueue, maxTesters=maxTester, cooldown=cooldown)
    queue.setup(listGamemodes)
except Exception as e:
    logging.exception("Setting up queue failed:")
    sys.exit("Error: Failed to setup queue")

def is_me(m):
    return m.author == bot.user

# ── Channel/role helpers ───────────────────────────────────────────────────────

def get_channel_by_name(name: str) -> nextcord.TextChannel | None:
    for guild in bot.guilds:
        ch = nextcord.utils.get(guild.text_channels, name=name)
        if ch:
            return ch
    return None

def get_category_by_name(guild: nextcord.Guild, name: str) -> nextcord.CategoryChannel | None:
    return nextcord.utils.get(guild.categories, name=name)

def get_role_by_name(guild: nextcord.Guild, name: str) -> nextcord.Role | None:
    return nextcord.utils.get(guild.roles, name=name)

def has_staff_role(member: nextcord.Member) -> bool:
    tester = roleNames["tester"]
    staff  = roleNames["staff"]
    return any(r.name in (tester, staff) for r in member.roles)

# ── Startup ────────────────────────────────────────────────────────────────────

async def setupBot():
    await databaseManager.createTables()

    for guild in bot.guilds:
        await ensure_all(guild)   # create any missing roles/channels/categories
        queue.resolveChannels(guild)

    # Post the Verify panel
    verify_ch = get_channel_by_name(channelNames["verify"])
    if verify_ch is None:
        sys.exit(f"Error: Channel '{channelNames['verify']}' not found")
    await verify_ch.purge(limit=10, check=is_me)
    await verify_ch.send(embed=nextcord.Embed.from_dict(format.verifymessage), view=VerifyPanelView())

    # Post the queue-select panel
    join_ch = get_channel_by_name(channelNames["join_queue"])
    if join_ch is None:
        sys.exit(f"Error: Channel '{channelNames['join_queue']}' not found")
    await join_ch.purge(limit=10, check=is_me)
    await join_ch.send(embed=nextcord.Embed.from_dict(format.enterwaitlistmessage), view=PanelView())

    # Post the no-queue embed in every gamemode queue channel
    for gm_key, gm_data in listGamemodes.items():
        gm_ch = get_channel_by_name(gm_data["queue_channel"])
        if gm_ch is None:
            logging.warning(f"Queue channel '{gm_data['queue_channel']}' not found for gamemode '{gm_key}'")
            continue
        await gm_ch.purge(limit=10, check=is_me)
        await gm_ch.send(embed=nextcord.Embed.from_dict(format.formatnoqueue()))


@bot.event
async def on_ready():
    print("Tier Testing bot has logged online ✅")
    bot.add_view(VerifyPanelView())  # register persistent view for the Verify button
    bot.add_view(PanelView())  # register persistent view for buttons to work after restart
    try:
        await bot.sync_all_application_commands()
        print("Slash commands synced ✅")
        await setupBot()
        updateQueue.start()
    except Exception as e:
        logging.exception("Failed bot startup sequence:")
        sys.exit("Failed startup sequence")


@tasks.loop(seconds=reloadQueue)
async def updateQueue():
    queues = queue.getqueueraw()
    for gamemode, data in queues.items():
        if not data["open"]:
            continue
        messageID = data["queueMessage"]
        if messageID is None:
            continue
        channel = bot.get_channel(data["queueChannel"])
        if channel is None:
            continue
        message: nextcord.Message = await channel.fetch_message(messageID)
        messageUpdate = queue.makeQueueMessage(gamemode=gamemode)
        await message.edit(embed=nextcord.Embed.from_dict(messageUpdate))


# ── Slash commands ─────────────────────────────────────────────────────────────

@bot.slash_command(name="results", description="Closes a ticket and assigns a tier to a player")
async def results(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Their Discord account", required=True),
    newtier: str = nextcord.SlashOption(description="Their new tier", required=True, choices=listTiers),
    gamemode: str = nextcord.SlashOption(description="Gamemode tested", required=True, choices=listGamemodesText),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        exists = await databaseManager.userExists(user.id)
        if not exists:
            await interaction.response.send_message("User does not exist in the database.", ephemeral=True); return

        if await databaseManager.isRestriced(interaction.user.id):
            await interaction.response.send_message("You are currently restricted.", ephemeral=True); return

        if await databaseManager.isRestriced(user.id):
            await interaction.response.send_message("That user is restricted.", ephemeral=True); return

        gm_key = gamemodeDisplayToKey.get(gamemode, gamemode)
        username, oldtier, _ = await databaseManager.getResultInfo(user.id)
        uuid = await mojang.getuserid(username=username)

        result_embed_data = format.formatresult(
            discordUsername=user.name,
            testerID=interaction.user.id,
            gamemode=gamemode,
            minecraftUsername=username,
            oldTier=oldtier,
            newTier=newtier,
            uuid=uuid
        )
        embed = nextcord.Embed.from_dict(result_embed_data)
        await databaseManager.addResult(discordID=user.id, tier=newtier, gamemode=gm_key)

        member = interaction.guild.get_member(user.id)

        # Only remove the waitlist role for the gamemode that was tested
        gm_waitlist_role_name = get_waitlist_role_name(gm_key)
        gm_waitlist_role = get_role_by_name(interaction.guild, gm_waitlist_role_name)
        if gm_waitlist_role and gm_waitlist_role in member.roles:
            await member.remove_roles(gm_waitlist_role, reason="Waitlist role removed by /results")

        # Remove the generic Waitlist role only if they hold no other gamemode waitlist roles
        remaining_waitlist = [
            get_waitlist_role_name(k) for k in listGamemodeKeys if k != gm_key
        ]
        has_other_waitlist = any(
            r.name in remaining_waitlist for r in member.roles
        )
        if not has_other_waitlist:
            generic_role = get_role_by_name(interaction.guild, roleNames["waitlist"])
            if generic_role and generic_role in member.roles:
                await member.remove_roles(generic_role, reason="No remaining waitlist roles")

        # Remove any existing tier roles for this gamemode
        old_tier_role_names = [get_tier_role_name(gm_key, t) for t in tierOrder]
        old_tier_roles = [r for r in member.roles if r.name in old_tier_role_names]
        if old_tier_roles:
            await member.remove_roles(*old_tier_roles, reason="Old tier roles removed by /results")

        # Add new tier role
        if newtier != "none":
            new_role_name = get_tier_role_name(gm_key, newtier)
            new_role = get_role_by_name(interaction.guild, new_role_name)
            if new_role:
                await member.add_roles(new_role, reason="New tier role added by /results")
            else:
                logging.warning(f"Tier role '{new_role_name}' not found in guild")

        announcements_ch = get_channel_by_name(channelNames["announcements"])
        if announcements_ch:
            await announcements_ch.send(content=f"<@{user.id}>", embed=embed)

        # ── Push this result straight to the website's data.json on GitHub ──
        site_warning = ""
        try:
            site_mode = github.site_mode_key(gm_key)
            site_tier = None if newtier == "none" else newtier
            gh_data, gh_sha = github.fetch_data()
            github.set_player_tier(gh_data, site_mode, username, site_tier)
            gh_data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
            github.push_data(
                gh_data, gh_sha,
                f"/results {username} -> {site_mode}/{newtier} (by {interaction.user.name})"
            )
        except Exception:
            logging.exception("Failed to push /results to the website's data.json:")
            site_warning = "\n⚠️ Result posted, but the website update failed — check logs / GITHUB_TOKEN."

        await interaction.response.send_message(content=messages["result_sent"] + site_warning, ephemeral=True)
    except Exception as e:
        logging.exception("Error in /results:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="openqueue", description="Opens a queue for a gamemode")
async def openqueue(
    interaction: nextcord.Interaction,
    gamemode: str = nextcord.SlashOption(description="Gamemode", required=True, choices=listGamemodesText),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        gm_key = gamemodeDisplayToKey.get(gamemode, gamemode)
        response = queue.addTester(gamemode=gm_key, userID=interaction.user.id)

        if response[1] != "":
            gm_ch = get_channel_by_name(listGamemodes[gm_key]["queue_channel"])
            if gm_ch is None:
                await interaction.response.send_message(content=messages["error"], ephemeral=True); return

            ping_role = get_role_by_name(interaction.guild, listGamemodes[gm_key]["role_ping"])
            ping_content = f"<@&{ping_role.id}>" if ping_role else ""

            await gm_ch.purge(limit=10, check=is_me)
            queueMessage: nextcord.Message = await gm_ch.send(
                content=ping_content,
                embed=nextcord.Embed.from_dict(response[1]),
                view=EnterQueueButton(queue=queue)
            )
            queue.addQueueMessageId(gamemode=gm_key, messageID=queueMessage.id)

        await interaction.response.send_message(content=response[0], ephemeral=True)
    except Exception as e:
        logging.exception("Error in /openqueue:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="closequeue", description="Stops you testing a gamemode — queue stays open if other testers remain")
async def closequeue(
    interaction: nextcord.Interaction,
    gamemode: str = nextcord.SlashOption(description="Gamemode", required=True, choices=listGamemodesText),
):
    try:
        gm_key = gamemodeDisplayToKey.get(gamemode, gamemode)
        response = queue.removeTester(userID=interaction.user.id, gamemode=gm_key)
        if response == "Testing is closed":
            await interaction.response.send_message(content=response, ephemeral=True); return

        message_text, embed_data, channel_id, message_id = response
        queueChannel = bot.get_channel(channel_id)
        queueMessage = await queueChannel.fetch_message(message_id)

        if isinstance(embed_data, dict):
            if message_text == "testing has closed":
                await queueMessage.edit(embed=nextcord.Embed.from_dict(embed_data), view=None)
            else:
                await queueMessage.edit(embed=nextcord.Embed.from_dict(embed_data))
        else:
            await interaction.response.send_message("Something went wrong with the queue embed.", ephemeral=True); return

        await interaction.response.send_message(content=message_text, ephemeral=True)
    except Exception as e:
        logging.exception("Error in /closequeue:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="forceclosequeue", description="Closes a gamemode's queue for every tester currently testing it")
async def forceclosequeue(
    interaction: nextcord.Interaction,
    gamemode: str = nextcord.SlashOption(description="Gamemode", required=True, choices=listGamemodesText),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        gm_key = gamemodeDisplayToKey.get(gamemode, gamemode)
        response = queue.forceCloseQueue(gamemode=gm_key)
        if response == "Testing is closed":
            await interaction.response.send_message(content=response, ephemeral=True); return

        message_text, embed_data, channel_id, message_id = response
        queueChannel = bot.get_channel(channel_id)
        queueMessage = await queueChannel.fetch_message(message_id)

        if isinstance(embed_data, dict):
            await queueMessage.edit(embed=nextcord.Embed.from_dict(embed_data), view=None)
        else:
            await interaction.response.send_message("Something went wrong with the queue embed.", ephemeral=True); return

        await interaction.response.send_message(content=message_text, ephemeral=True)
    except Exception as e:
        logging.exception("Error in /forceclosequeue:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="next", description="Gets the next player to test")
async def next(
    interaction: nextcord.Interaction,
    gamemode: str = nextcord.SlashOption(description="Gamemode", required=True, choices=listGamemodesText),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        gm_key = gamemodeDisplayToKey.get(gamemode, gamemode)

        if interaction.user.id not in queue.queue[gm_key]["testers"]:
            await interaction.response.send_message("You are not testing this gamemode!", ephemeral=True); return

        user_result = queue.getNextTest(testerID=interaction.user.id, gamemode=gm_key)
        if user_result[0] is None:
            await interaction.response.send_message(content=user_result[1], ephemeral=True); return

        member: nextcord.Member = await interaction.guild.fetch_member(user_result[0])

        # ── Cooldown check happens at TEST time, not at join time ──────────
        # Players can hold the waitlist role while on cooldown, but can't
        # actually be tested for that specific gamemode until it expires.
        member_cooldown = get_cooldown_for_member(member)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        cd_row = await databaseManager.getLastTestForGamemode(member.id, gm_key)
        last_test = cd_row[0] if cd_row else 0
        if now_ts - last_test <= member_cooldown * 60:
            unlock_ts = last_test + (member_cooldown * 60)
            await interaction.response.send_message(
                f"❌ Can't test **{member.display_name}** — they're on cooldown for **{listGamemodes[gm_key]['display']}** "
                f"until <t:{unlock_ts}:f> (<t:{unlock_ts}:R>).\n"
                f"They've been removed from this queue — they'll need to rejoin the waitlist once their cooldown ends.",
                ephemeral=True
            )
            return

        ticket_cat = get_category_by_name(interaction.guild, ticketCategoryName)
        if ticket_cat is None:
            await interaction.response.send_message(content=messages["error"], ephemeral=True); return

        channel_name = ticketChannelTemplate.format(ign=member.name, gamemode=gm_key)
        ticket_ch = await interaction.guild.create_text_channel(category=ticket_cat, name=channel_name)
        overwrite = nextcord.PermissionOverwrite(view_channel=True, send_messages=True)
        await ticket_ch.set_permissions(member, overwrite=overwrite)

        messageData = await databaseManager.getUserTicket(member.id)
        ticketMessage = format.formatticketmessage(username=messageData[0], tier=messageData[1], uuid=messageData[3])

        # Only remove the waitlist role for the gamemode being tested
        gm_waitlist_role_name = get_waitlist_role_name(gm_key)
        gm_waitlist_role = get_role_by_name(interaction.guild, gm_waitlist_role_name)
        if gm_waitlist_role and gm_waitlist_role in member.roles:
            await member.remove_roles(gm_waitlist_role)

        # Remove the generic Waitlist role only if they hold no other gamemode waitlist roles
        remaining_waitlist = [
            get_waitlist_role_name(k) for k in listGamemodeKeys if k != gm_key
        ]
        has_other_waitlist = any(r.name in remaining_waitlist for r in member.roles)
        if not has_other_waitlist:
            generic_role = get_role_by_name(interaction.guild, roleNames["waitlist"])
            if generic_role and generic_role in member.roles:
                await member.remove_roles(generic_role)

        await ticket_ch.send(content=f"<@{member.id}>", embed=nextcord.Embed.from_dict(ticketMessage))
        await interaction.response.send_message(f"Ticket created: <#{ticket_ch.id}>", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /next:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="closetest", description="Closes the current test ticket (10s delay)")
async def closetest(interaction: nextcord.Interaction):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        cat = interaction.channel.category
        valid_cats = [ticketCategoryName, highTicketCategoryName]
        if cat is None or cat.name not in valid_cats or interaction.channel.name in listGamemodeQueueChannelNames:
            await interaction.response.send_message(messages["not_ticket_category"], ephemeral=True); return

        view = CloseTicketButton()
        await interaction.response.send_message("Ticket will be closed in 10 seconds", view=view)
        await asyncio.sleep(10)
        if not view.cancelled:
            await post_transcript(interaction.channel, interaction.guild, interaction.user)
            await interaction.channel.delete(reason="Ticket closed by /closetest")
    except Exception as e:
        logging.exception("Error in /closetest:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="forceclosetest", description="Closes the current test ticket immediately (no cancel)")
async def forceclosetest(interaction: nextcord.Interaction):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        cat = interaction.channel.category
        valid_cats = [ticketCategoryName, highTicketCategoryName]
        if cat is None or cat.name not in valid_cats or interaction.channel.name in listGamemodeQueueChannelNames:
            await interaction.response.send_message(messages["not_ticket_category"], ephemeral=True); return

        await interaction.response.send_message("Ticket will be closed in 10 seconds, this cannot be cancelled.")
        await asyncio.sleep(10)
        await post_transcript(interaction.channel, interaction.guild, interaction.user)
        await interaction.channel.delete(reason="Ticket force-closed by /forceclosetest")
    except Exception as e:
        logging.exception("Error in /forceclosetest:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="updateusername", description="Updates a player's stored Minecraft username")
async def updateusername(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
    username: str = nextcord.SlashOption(description="New Minecraft username", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return
        if not await databaseManager.userExists(user.id):
            await interaction.response.send_message("User not found in database.", ephemeral=True); return

        uuid = await mojang.getuserid(username=username)
        if uuid == "8667ba71b85a4004af54457a9734eed7":
            await interaction.response.send_message("Minecraft username does not exist.", ephemeral=True); return

        await databaseManager.updateUsername(discordID=user.id, username=username, uuid=uuid)
        await interaction.response.send_message("Username updated successfully.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /updateusername:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="updatetier", description="Updates a player's tier in the database")
async def updatetier(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
    tier: str = nextcord.SlashOption(description="New tier", required=True, choices=listTiers),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return
        if not await databaseManager.userExists(user.id):
            await interaction.response.send_message("User not found in database.", ephemeral=True); return

        await databaseManager.updateTier(discordID=user.id, tier=tier)
        await interaction.response.send_message("Tier updated in database. Remember to update their roles too.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /updatetier:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="restrict", description="Restricts a player from queuing")
async def restrict(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return
        if not await databaseManager.userExists(user.id):
            await interaction.response.send_message("User not found in database.", ephemeral=True); return

        await databaseManager.updateRestriction(discordID=user.id, restricted=True)
        await interaction.response.send_message("User has been restricted.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /restrict:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="unrestrict", description="Removes a restriction from a player")
async def unrestrict(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return
        if not await databaseManager.userExists(user.id):
            await interaction.response.send_message("User not found in database.", ephemeral=True); return

        await databaseManager.updateRestriction(discordID=user.id, restricted=False)
        await interaction.response.send_message("User has been unrestricted.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /unrestrict:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="removecooldown", description="Removes the queue cooldown for a player")
async def removecooldown(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return
        if not await databaseManager.userExists(user.id):
            await interaction.response.send_message("User not found in database.", ephemeral=True); return

        await databaseManager.resetCooldown(discordID=user.id)
        await databaseManager.resetGamemodeCooldowns(discordID=user.id)
        await interaction.response.send_message(f"Cooldown removed for {user.mention}. They can queue immediately.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /removecooldown:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="info", description="Shows stored info for a player")
async def info(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not await databaseManager.userExists(user.id):
            await interaction.response.send_message("User not found in database.", ephemeral=True); return

        result = await databaseManager.getUserInfo(user.id)
        username, tier, lastTest, gamemode, restricted, uuid = result

        await interaction.response.send_message(embed=nextcord.Embed.from_dict(
            format.formatinfo(discordName=str(user.name), username=username, tier=tier,
                              lastTest=lastTest, gamemode=gamemode, restricted=restricted, uuid=uuid)
        ))
    except Exception as e:
        logging.exception("Error in /info:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="syncusername", description="Re-fetch a player's current Minecraft username (if they changed IGN) and update their nickname")
async def syncusername(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return
        if not await databaseManager.userExists(user.id):
            await interaction.response.send_message("User not found in database.", ephemeral=True); return

        await interaction.response.defer(ephemeral=True)

        info = await databaseManager.getUserInfo(user.id)
        old_username, _, _, _, _, uuid = info

        current_username = await mojang.getusername(uuid)
        if current_username is None:
            await interaction.followup.send(
                f"⚠️ Couldn't resolve UUID `{uuid}` — Mojang API may be down, or the account no longer exists.",
                ephemeral=True
            )
            return

        if current_username == old_username:
            await interaction.followup.send(
                f"✅ **{old_username}** is already up to date.\n-# uuid: `{uuid}` · mojang returned: `{current_username}`",
                ephemeral=True
            )
            return

        await databaseManager.updateUsername(discordID=user.id, username=current_username, uuid=uuid)

        nick_note = ""
        member = interaction.guild.get_member(user.id)
        if member:
            try:
                await member.edit(nick=current_username[:32])
            except nextcord.Forbidden:
                nick_note = "\n⚠️ Couldn't update their nickname (permissions/role hierarchy)."
            except Exception:
                nick_note = "\n⚠️ Couldn't update their nickname."

        await interaction.followup.send(
            f"✅ Username updated: **{old_username}** → **{current_username}**.{nick_note}",
            ephemeral=True
        )
    except Exception as e:
        logging.exception("Error in /syncusername:")
        await interaction.followup.send(content=messages["error"], ephemeral=True)


@bot.slash_command(name="syncallusernames", description="Re-fetch current Minecraft usernames for every verified player (bulk)")
async def syncallusernames(interaction: nextcord.Interaction):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        await interaction.response.defer(ephemeral=True)

        users = await databaseManager.getAllUsers()
        if not users:
            await interaction.followup.send("No users found in the database.", ephemeral=True)
            return

        updated, unchanged, failed, nick_failed = 0, 0, 0, 0
        changes = []

        for discordID, old_username, uuid in users:
            try:
                current_username = await mojang.getusername(uuid)
                if current_username is None:
                    failed += 1
                    continue
                if current_username == old_username:
                    unchanged += 1
                    continue

                await databaseManager.updateUsername(discordID=discordID, username=current_username, uuid=uuid)
                changes.append(f"**{old_username}** → **{current_username}**")
                updated += 1

                member = interaction.guild.get_member(discordID)
                if member:
                    try:
                        await member.edit(nick=current_username[:32])
                    except Exception:
                        nick_failed += 1
            except Exception:
                failed += 1

            await asyncio.sleep(0.6)  # be gentle with the Mojang API

        summary = (
            f"✅ Sync complete.\n"
            f"**{updated}** updated, **{unchanged}** already current, **{failed}** failed to resolve"
            + (f", **{nick_failed}** nickname updates failed" if nick_failed else "") + "."
        )
        if changes:
            preview = "\n".join(changes[:20])
            if len(changes) > 20:
                preview += f"\n…and {len(changes) - 20} more."
            summary += "\n\n" + preview

        await interaction.followup.send(summary, ephemeral=True)
    except Exception as e:
        logging.exception("Error in /syncallusernames:")
        await interaction.followup.send(content=messages["error"], ephemeral=True)


@bot.slash_command(name="add", description="Adds a user to the current ticket channel")
async def add(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        cat = interaction.channel.category
        valid_cats = [ticketCategoryName, highTicketCategoryName]
        if cat is None or cat.name not in valid_cats:
            await interaction.response.send_message(messages["not_ticket_category"], ephemeral=True); return

        overwrite = nextcord.PermissionOverwrite(view_channel=True, send_messages=True)
        await interaction.channel.set_permissions(user, overwrite=overwrite)
        await interaction.response.send_message(f"<@{user.id}> has been added to the ticket!")
    except Exception as e:
        logging.exception("Error in /add:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="remove", description="Removes a user from the current ticket channel")
async def remove(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        cat = interaction.channel.category
        valid_cats = [ticketCategoryName, highTicketCategoryName]
        if cat is None or cat.name not in valid_cats:
            await interaction.response.send_message(messages["not_ticket_category"], ephemeral=True); return

        overwrite = nextcord.PermissionOverwrite(view_channel=False, send_messages=False)
        await interaction.channel.set_permissions(user, overwrite=overwrite)
        await interaction.response.send_message(f"<@{user.id}> has been removed from the ticket!")
    except Exception as e:
        logging.exception("Error in /remove:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


@bot.slash_command(name="passeval", description="Marks the current ticket channel as passed eval")
async def passeval(
    interaction: nextcord.Interaction,
    user: nextcord.User = nextcord.SlashOption(description="Discord account", required=True),
):
    try:
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(messages["no_permission"], ephemeral=True); return

        cat = interaction.channel.category
        valid_cats = [ticketCategoryName, highTicketCategoryName]
        if cat is None or cat.name not in valid_cats or interaction.channel.name in listGamemodeQueueChannelNames:
            await interaction.response.send_message(messages["not_ticket_category"], ephemeral=True); return

        await interaction.channel.edit(name=f"passeval-{user.name}")
        await interaction.response.send_message(f"<@{user.id}> has passed eval!")
    except Exception as e:
        logging.exception("Error in /passeval:")
        await interaction.response.send_message(content=messages["error"], ephemeral=True)


# ── /tier — website data.json admin commands (merged from the old bot) ─────────

@bot.slash_command(name="tier", description="Manage the website's tier list data")
async def tier(interaction: nextcord.Interaction):
    pass  # parent command — never invoked directly, only its subcommands are


@tier.subcommand(name="set", description="Place a player in a tier for a mode on the website")
async def tier_set(
    interaction: nextcord.Interaction,
    mode: str = nextcord.SlashOption(description="Game mode", required=True, choices=github.MODES),
    tier: str = nextcord.SlashOption(description="Tier code", required=True, choices=github.TIERS),
    player: str = nextcord.SlashOption(description="Minecraft username (exact capitalisation)", required=True),
):
    if not has_staff_role(interaction.user):
        return await interaction.response.send_message(messages["no_permission"], ephemeral=True)

    player = player.strip()
    await interaction.response.defer(ephemeral=True)
    try:
        data, sha = github.fetch_data()
        github.set_player_tier(data, mode, player, tier)
        data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
        github.push_data(data, sha, f"set {player} -> {mode}/{tier} (by {interaction.user.name})")
        await interaction.followup.send(f"✅ **{player}** is now **{tier}** in **{mode}**.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /tier set:")
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


@tier.subcommand(name="remove", description="Remove a player from a mode on the website entirely")
async def tier_remove(
    interaction: nextcord.Interaction,
    mode: str = nextcord.SlashOption(description="Game mode", required=True, choices=github.MODES),
    player: str = nextcord.SlashOption(description="Minecraft username", required=True),
):
    if not has_staff_role(interaction.user):
        return await interaction.response.send_message(messages["no_permission"], ephemeral=True)

    player = player.strip()
    await interaction.response.defer(ephemeral=True)
    try:
        data, sha = github.fetch_data()
        github.ensure_structure(data)

        removed = False
        for t in github.TIERS:
            before = len(data["placements"][mode][t])
            data["placements"][mode][t] = [
                n for n in data["placements"][mode][t] if n.lower() != player.lower()
            ]
            if len(data["placements"][mode][t]) < before:
                removed = True

        if not removed:
            return await interaction.followup.send(f"⚠️ **{player}** wasn't in any tier for **{mode}**.", ephemeral=True)

        data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
        github.push_data(data, sha, f"remove {player} from {mode} (by {interaction.user.name})")
        await interaction.followup.send(f"✅ **{player}** removed from **{mode}**.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /tier remove:")
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


@tier.subcommand(name="setregion", description="Set a player's region on the website")
async def tier_setregion(
    interaction: nextcord.Interaction,
    player: str = nextcord.SlashOption(description="Minecraft username", required=True),
    region: str = nextcord.SlashOption(description="NA, EU, AU or AS", required=True, choices=github.REGIONS),
):
    if not has_staff_role(interaction.user):
        return await interaction.response.send_message(messages["no_permission"], ephemeral=True)

    player = player.strip()
    await interaction.response.defer(ephemeral=True)
    try:
        data, sha = github.fetch_data()
        github.ensure_structure(data)
        data["playerMeta"].setdefault(player, {})["region"] = region
        data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
        github.push_data(data, sha, f"set {player} region={region} (by {interaction.user.name})")
        await interaction.followup.send(f"✅ **{player}**'s region set to **{region}**.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /tier setregion:")
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


@tier.subcommand(name="settester", description="Mark or unmark a player as a Tier Tester on the website")
async def tier_settester(
    interaction: nextcord.Interaction,
    player: str = nextcord.SlashOption(description="Minecraft username", required=True),
    is_tester: bool = nextcord.SlashOption(description="True to mark as tester, False to remove", required=True),
):
    if not has_staff_role(interaction.user):
        return await interaction.response.send_message(messages["no_permission"], ephemeral=True)

    player = player.strip()
    await interaction.response.defer(ephemeral=True)
    try:
        data, sha = github.fetch_data()
        github.ensure_structure(data)
        data["playerMeta"].setdefault(player, {})["tester"] = bool(is_tester)
        data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
        github.push_data(data, sha, f"set {player} tester={is_tester} (by {interaction.user.name})")
        status = "is now a **Tier Tester** ⭐" if is_tester else "is no longer a Tier Tester"
        await interaction.followup.send(f"✅ **{player}** {status}.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /tier settester:")
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


@tier.subcommand(name="setstaff", description="Set or clear a player's staff role on the website")
async def tier_setstaff(
    interaction: nextcord.Interaction,
    player: str = nextcord.SlashOption(description="Minecraft username", required=True),
    role: str = nextcord.SlashOption(
        description="Owner, Developer, High Staff, or None to remove",
        required=True,
        choices=["Owner", "Developer", "High Staff", "None"],
    ),
):
    if not has_staff_role(interaction.user):
        return await interaction.response.send_message(messages["no_permission"], ephemeral=True)

    player = player.strip()
    await interaction.response.defer(ephemeral=True)
    try:
        data, sha = github.fetch_data()
        github.ensure_structure(data)

        if role == "None":
            if player in data["playerMeta"]:
                data["playerMeta"][player].pop("staff", None)
            data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
            github.push_data(data, sha, f"clear {player} staff role (by {interaction.user.name})")
            await interaction.followup.send(f"✅ **{player}**'s staff role removed.", ephemeral=True)
        else:
            data["playerMeta"].setdefault(player, {})["staff"] = role
            data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
            github.push_data(data, sha, f"set {player} staff={role} (by {interaction.user.name})")
            await interaction.followup.send(f"✅ **{player}** is now **{role}**.", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /tier setstaff:")
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


@tier.subcommand(name="view", description="View current tiers for a mode on the website")
async def tier_view(
    interaction: nextcord.Interaction,
    mode: str = nextcord.SlashOption(description="Game mode to view", required=True, choices=github.MODES),
):
    await interaction.response.defer(ephemeral=True)
    try:
        data, _ = github.fetch_data()
        github.ensure_structure(data)

        lines = [f"**{mode.upper()} Rankings**\n"]
        for t in github.TIERS:
            players = [n for n in data["placements"][mode].get(t, []) if n.strip()]
            if players:
                lines.append(f"**{t}**: {', '.join(players)}")

        if len(lines) == 1:
            lines.append("_(no players placed yet)_")

        await interaction.followup.send("\n".join(lines), ephemeral=True)
    except Exception as e:
        logging.exception("Error in /tier view:")
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


@tier.subcommand(name="reload", description="Check the website's GitHub connection and file validity")
async def tier_reload(interaction: nextcord.Interaction):
    if not has_staff_role(interaction.user):
        return await interaction.response.send_message(messages["no_permission"], ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        data, _ = github.fetch_data()
        count = sum(
            len([n for n in data["placements"].get(m, {}).get(t, []) if n.strip()])
            for m in github.MODES for t in github.TIERS
        )
        lu = data.get("lastUpdated", "unknown")
        await interaction.followup.send(
            f"✅ Connected to `{github.GITHUB_REPO}`\n**{count}** total placements\nLast updated: `{lu}`",
            ephemeral=True)
    except Exception as e:
        logging.exception("Error in /tier reload:")
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


if __name__ == "__main__":
    bot.run(os.getenv("TOKEN"))
