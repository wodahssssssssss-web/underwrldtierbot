
# tier-test bot

A discord bot for minecraft tierlists that can be self hosted


## Installation

- create a discord bot at [discord dev portal](https://discord.com/developers/applications)

- turn on all intents in the bot section


```
git clone https://github.com/gmi/tier-test-bot.git

```
```
cd .\tier-test-bot
```

- you will now want to setup `config/config.yml` and make the `.env`

### `.env` file

```
TOKEN=your-discord-bot-token

# Website data.json sync (used by /tier commands and /results)
GITHUB_TOKEN=your-github-personal-access-token
GITHUB_REPO=username/underwrldtiers
GITHUB_FILE_PATH=data.json
```

```
pip install -r requirements.txt
```
```
python main.py
```

## Website sync (`/tier` commands)

This bot also manages the Underwrld Tiers website's `data.json` directly on GitHub —
the old standalone tier bot has been merged in, so there's now only one bot to run.

```
/tier set    <mode> <tier> <player>      — place a player in a tier
/tier remove <mode> <player>             — remove a player from a mode
/tier setregion <player> <region>        — set NA / EU / AU / AS
/tier settester <player> <true/false>    — mark/unmark a player as Tier Tester
/tier setstaff <player> <role>           — set staff role: Owner / Developer / High Staff / None
/tier view   <mode>                      — show current tiers for a mode
/tier reload                             — verify GitHub connection
```

`/results` now also pushes the outcome straight to the website automatically —
no need to also run `/tier set` after closing a ticket. Gamemode keys are mapped
to the website's mode keys where they differ: `netherite` → `nethop`, `crystal` → `vanilla`.

All `/tier` commands require the same staff/tester role check (`roles.tester` /
`roles.staff` in `config.yml`) as the rest of the bot's admin commands.
