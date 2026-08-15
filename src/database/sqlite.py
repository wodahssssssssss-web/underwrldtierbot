import sqlite3
import datetime

def withConnection(func):
    async def wrapper(*args, **kwargs):
        connection = sqlite3.connect('storage/database.db')
        try:
            cursor = connection.cursor()
            result = await func(cursor, *args, **kwargs)
            connection.commit()
            return result
        except Exception as e:
            connection.rollback()
            print(e)
            return False
        finally:
            connection.close()
    return wrapper

@withConnection
async def createTables(cursor: sqlite3.Cursor) -> bool:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        discordID INTEGER PRIMARY KEY,
        minecraftUsername TEXT NOT NULL,
        minecraftUUID TEXT NOT NULL,
        tier TEXT NOT NULL,
        lastTest INTEGER NOT NULL,
        server TEXT NOT NULL,
        gamemode TEXT NOT NULL,
        restricted BOOLEAN NOT NULL
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gamemode_cooldowns (
        discordID INTEGER NOT NULL,
        gamemode TEXT NOT NULL,
        lastTest INTEGER NOT NULL,
        PRIMARY KEY (discordID, gamemode)
    )""")
    # Migration: add `tier` column for existing DBs created before per-gamemode tiers existed
    cursor.execute("PRAGMA table_info(gamemode_cooldowns)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    if "tier" not in existing_cols:
        cursor.execute("ALTER TABLE gamemode_cooldowns ADD COLUMN tier TEXT DEFAULT 'none'")
    return True

@withConnection
async def addUser(cursor: sqlite3.Cursor, discordID: int, minecraftUsername: str, minecraftUUID: str, tier: str, lastTest: int, server: str, gamemode: str) -> bool:
    cursor.execute("""
    INSERT INTO users (discordID, minecraftUsername, minecraftUUID, tier, lastTest, server, gamemode, restricted)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(discordID) DO UPDATE SET
        minecraftUsername = excluded.minecraftUsername,
        minecraftUUID = excluded.minecraftUUID,
        server = excluded.server,
        gamemode = excluded.gamemode
    """, (discordID, minecraftUsername, minecraftUUID, tier, lastTest, server, gamemode, False))
    return True

@withConnection
async def getUserTicket(cursor: sqlite3.Cursor, discordID: int):
    cursor.execute("""
    SELECT minecraftUsername, tier, server, minecraftUUID FROM users WHERE discordID = ?
    """, (discordID,))

    return cursor.fetchone()


@withConnection
async def getResultInfo(cursor: sqlite3.Cursor, discordID: int):
    cursor.execute("""
    SELECT minecraftUsername, tier, gamemode FROM users WHERE discordID = ?
    """, (discordID,))

    return cursor.fetchone()


@withConnection
async def addResult(cursor: sqlite3.Cursor, discordID: int, tier: str, gamemode: str) -> bool:
    lastTest = int(datetime.datetime.now().timestamp())
    cursor.execute("""
    UPDATE users
        SET tier = ?, lastTest = ?, gamemode = ?
    WHERE
        discordID = ?    
    """, (tier, lastTest, gamemode, discordID))
    cursor.execute("""
    INSERT INTO gamemode_cooldowns (discordID, gamemode, lastTest, tier)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(discordID, gamemode) DO UPDATE SET lastTest = excluded.lastTest, tier = excluded.tier
    """, (discordID, gamemode, lastTest, tier))
    return True

@withConnection
async def getLastTestForGamemode(cursor: sqlite3.Cursor, discordID: int, gamemode: str):
    cursor.execute("""
    SELECT lastTest FROM gamemode_cooldowns WHERE discordID = ? AND gamemode = ?
    """, (discordID, gamemode))
    return cursor.fetchone()

@withConnection
async def getTierForGamemode(cursor: sqlite3.Cursor, discordID: int, gamemode: str):
    cursor.execute("""
    SELECT tier FROM gamemode_cooldowns WHERE discordID = ? AND gamemode = ?
    """, (discordID, gamemode))
    return cursor.fetchone()

@withConnection
async def setTierForGamemodeSync(cursor: sqlite3.Cursor, discordID: int, gamemode: str, tier: str) -> bool:
    """Upserts a player's tier for a gamemode WITHOUT touching lastTest on existing rows
    (used by the website->DB sync, which has no cooldown-timestamp data to give)."""
    cursor.execute("""
    INSERT INTO gamemode_cooldowns (discordID, gamemode, lastTest, tier)
    VALUES (?, ?, 0, ?)
    ON CONFLICT(discordID, gamemode) DO UPDATE SET tier = excluded.tier
    """, (discordID, gamemode, tier))
    return True

@withConnection
async def resetGamemodeCooldowns(cursor: sqlite3.Cursor, discordID: int) -> bool:
    cursor.execute("DELETE FROM gamemode_cooldowns WHERE discordID = ?", (discordID,))
    return True

@withConnection
async def userExists(cursor: sqlite3.Cursor, discordID: int) -> bool:
    cursor.execute("SELECT 1 FROM users WHERE discordID = ? LIMIT 1", (discordID,))
    return cursor.fetchone() is not None

@withConnection
async def getLastTest(cursor: sqlite3.Cursor, discordID: int):
    cursor.execute("SELECT lastTest FROM users WHERE discordID = ?", (discordID,))
    return cursor.fetchone()

@withConnection
async def getTier(cursor: sqlite3.Cursor, discordID: int):
    cursor.execute("SELECT tier FROM users WHERE discordID = ?", (discordID,))
    return cursor.fetchone()

@withConnection
async def isRestricted(cursor: sqlite3.Cursor, discordID: int) -> bool:
    cursor.execute("SELECT restricted FROM users WHERE discordID = ?", (discordID,))
    result = cursor.fetchone()
    return result[0] if result else False

@withConnection
async def updateUsername(cursor: sqlite3.Cursor, discordID: int, username: str, uuid: int) -> bool:
    cursor.execute("""
    UPDATE users
        SET minecraftUsername = ?, minecraftUUID = ?
    WHERE
        discordID = ?    
    """, (username, uuid, discordID))
    return True

@withConnection
async def updateTier(cursor: sqlite3.Cursor, discordID: int, tier: str) -> bool:
    cursor.execute("""
    UPDATE users
        SET tier = ?
    WHERE
        discordID = ?    
    """, (tier, discordID))
    return True

@withConnection
async def updateRestriction(cursor: sqlite3.Cursor, discordID: int, restricted: bool) -> bool:
    cursor.execute("""
    UPDATE users
        SET restricted = ?
    WHERE
        discordID = ?    
    """, (restricted, discordID))
    return True

@withConnection
async def resetCooldown(cursor: sqlite3.Cursor, discordID: int) -> bool:
    cursor.execute("""
    UPDATE users
        SET lastTest = 0
    WHERE
        discordID = ?
    """, (discordID,))
    return True

@withConnection
async def getUserInfo(cursor: sqlite3.Cursor, discordID: int):
    cursor.execute("""
    SELECT minecraftUsername, tier, lastTest, gamemode, restricted, minecraftUUID 
    FROM users WHERE discordID = ?
    """, (discordID,))
    return cursor.fetchone()

@withConnection
async def getAllUsers(cursor: sqlite3.Cursor):
    cursor.execute("SELECT discordID, minecraftUsername, minecraftUUID FROM users")
    return cursor.fetchall()
