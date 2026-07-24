import nextcord
from nextcord import ui

from src.utils.loadConfig import messages, channelNames
from src.tierlistQueue import TierlistQueue
from src.database import databaseManager


class EnterQueueButton(ui.View):
    def __init__(self, queue):
        super().__init__(timeout=None)
        self.queue: TierlistQueue = queue

    @nextcord.ui.button(label="Enter Queue", style=nextcord.ButtonStyle.primary, custom_id="joinQueue")
    async def enter_queue(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        try:
            exists = await databaseManager.userExists(interaction.user.id)
            if not exists:
                join_ch = nextcord.utils.get(interaction.guild.text_channels, name=channelNames["join_queue"])
                ch_mention = f"<#{join_ch.id}>" if join_ch else f"#{channelNames['join_queue']}"
                await interaction.response.send_message(
                    f"Please register first in {ch_mention}", ephemeral=True
                )
                return

            if await databaseManager.isRestriced(interaction.user.id):
                await interaction.response.send_message("You are currently restricted.", ephemeral=True)
                return

            response = self.queue.addUser(interaction.message.id, interaction.user.id)
            await interaction.response.send_message(content=response, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)

    @nextcord.ui.button(label="Leave Queue", style=nextcord.ButtonStyle.danger, custom_id="leaveQueue")
    async def exit_queue(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        try:
            response = self.queue.removeUser(interaction.message.id, interaction.user.id)
            await interaction.response.send_message(content=response, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(content=messages["error"], ephemeral=True)
