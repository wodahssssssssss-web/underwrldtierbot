from src.utils import format
from src.utils.loadConfig import *

class TierlistQueue():
    def __init__(self, maxQueue: int, maxTesters: int, cooldown: int):
        self.queue = {}
        self.maxQueue = maxQueue
        self.maxTesters = maxTesters
        self.cooldown = cooldown

    def setup(self, gamemodes: dict) -> None:
        for gm_name, gm_data in gamemodes.items():
            self.queue[gm_name] = {
                "queueChannelName": gm_data["queue_channel"],
                "queueChannel": None,       # resolved to channel ID after bot is ready
                "queueMessage": None,
                "pingRole": gm_data["role_ping"],
                "open": False,
                "testers": [],
                "queue": []
            }

    def resolveChannels(self, guild) -> None:
        """Call once on_ready to resolve channel names to IDs."""
        import nextcord
        for gm_name, data in self.queue.items():
            ch = nextcord.utils.get(guild.text_channels, name=data["queueChannelName"])
            if ch:
                self.queue[gm_name]["queueChannel"] = ch.id
            else:
                raise ValueError(f"Queue channel '{data['queueChannelName']}' not found for gamemode '{gm_name}'")

    def openqueue(self, queue: str, open: bool):
        self.queue[queue]["open"] = open
        if open == False:
            self.queue[queue]["queue"] = []
            self.queue[queue]["testers"] = []

    def addUser(self, messageID: int, userID: int):
        gamemode = ""
        for gm, data in self.queue.items():
            if data["queueMessage"] == messageID:
                gamemode = gm
                break

        if gamemode == "":
            return "Gamemode doesn't exist"
        
        if userID in self.queue[gamemode]["queue"]:
            return messages["already_in_queue"]
        
        if len(self.queue[gamemode]["queue"]) >= self.maxQueue:
            return messages["queue_full"]
        
        self.queue[gamemode]["queue"].append(userID)
        return messages["added_to_queue"]

    def removeUser(self, messageID: int, userID: int):
        gamemode = ""
        for gm, data in self.queue.items():
            if data["queueMessage"] == messageID:
                gamemode = gm
                break

        if gamemode == "":
            return "Gamemode doesn't exist"
        
        if userID not in self.queue[gamemode]["queue"]:
            return messages["not_in_queue"]
        
        self.queue[gamemode]["queue"].remove(userID)
        return messages["left_queue"]

    def addTester(self, gamemode: str, userID: int):
        if self.queue[gamemode]["testers"] == []:
            self.openqueue(queue=gamemode, open=True)
        
        if userID in self.queue[gamemode]["testers"]:
            return ("You are already testing this queue!", "")

        if len(self.queue[gamemode]["testers"]) < self.maxTesters:
            self.queue[gamemode]["testers"].append(userID)
            return (
                f"{messages['tester_opened_queue']}: <#{self.queue[gamemode]['queueChannel']}>",
                self.makeQueueMessage(gamemode=gamemode)
            )

    def forceCloseQueue(self, gamemode: str):
        if self.queue[gamemode]["open"] == False: return "Testing is closed"
        self.queue[gamemode]["testers"] = []
        self.openqueue(queue=gamemode, open=False)
        return ("testing has closed", format.formatnoqueue(), self.queue[gamemode]["queueChannel"], self.queue[gamemode]["queueMessage"])

    def removeTester(self, gamemode: str, userID: int):
        if self.queue[gamemode]["open"] == False: return "Testing is closed"

        if userID in self.queue[gamemode]["testers"]:
            self.queue[gamemode]["testers"].remove(userID)
            
            if self.queue[gamemode]["testers"] == []:
                self.openqueue(queue=gamemode, open=False)
                return ("testing has closed", format.formatnoqueue(), self.queue[gamemode]["queueChannel"], self.queue[gamemode]["queueMessage"])

            return ("you have stopped testing", self.makeQueueMessage(gamemode=gamemode), self.queue[gamemode]["queueChannel"], self.queue[gamemode]["queueMessage"])
        
        return ("you are not testing this gamemode", self.makeQueueMessage(gamemode=gamemode), self.queue[gamemode]["queueChannel"], self.queue[gamemode]["queueMessage"])

    def getNextTest(self, testerID: int, gamemode: str):
        if self.queue[gamemode]["queue"] == []:
            return (None, f"No users are in the queue for {gamemode}")
        user = self.queue[gamemode]["queue"].pop(0)
        return (user, None)

    def makeQueueMessage(self, gamemode: str):
        capacity = f"{len(self.queue[gamemode]['queue'])}/{self.maxQueue}"
        testerCapacity = f"{len(self.queue[gamemode]['testers'])}/{self.maxTesters}"
        queue = "\n".join([f"{i+1}. <@{user_id}>" for i, user_id in enumerate(self.queue[gamemode]["queue"])])
        testers = "\n".join([f"{i+1}. <@{user_id}>" for i, user_id in enumerate(self.queue[gamemode]["testers"])])
        return format.formatqueue(capacity=capacity, queue=queue, testerCapacity=testerCapacity, testers=testers)

    def addQueueMessageId(self, gamemode: str, messageID: int):
        self.queue[gamemode]["queueMessage"] = messageID

    def getqueueraw(self) -> dict:
        return self.queue
