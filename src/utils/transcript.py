"""
utils/transcript.py
====================
Builds a plain-text transcript of a ticket channel and posts it to the
tester-logs channel as a .txt attachment when the ticket is closed.
"""

from __future__ import annotations
import io
import datetime
import logging

import nextcord

from src.utils.loadConfig import channelNames

log = logging.getLogger(__name__)


async def build_transcript_text(channel: nextcord.TextChannel) -> str:
    """Fetches every message in *channel* (oldest first) and formats it as plain text."""
    lines: list[str] = [
        f"Transcript of #{channel.name}",
        f"Channel ID: {channel.id}",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]

    async for message in channel.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author = f"{message.author} ({message.author.id})"
        content = message.content or ""

        lines.append(f"[{timestamp}] {author}:")
        if content:
            lines.append(content)

        if message.embeds:
            for embed in message.embeds:
                lines.append("  [Embed]")
                if embed.title:
                    lines.append(f"  Title: {embed.title}")
                if embed.description:
                    lines.append(f"  Description: {embed.description}")
                for field in embed.fields:
                    lines.append(f"  {field.name}: {field.value}")

        if message.attachments:
            for attachment in message.attachments:
                lines.append(f"  [Attachment] {attachment.filename}: {attachment.url}")

        lines.append("")

    return "\n".join(lines)


async def post_transcript(channel: nextcord.TextChannel, guild: nextcord.Guild, closed_by: nextcord.Member) -> None:
    """
    Builds a transcript of *channel* and sends it as a .txt file to the
    configured tester-logs channel. Safe to call even if the channel is
    about to be deleted right after.
    """
    try:
        transcript_text = await build_transcript_text(channel)

        logs_channel = nextcord.utils.get(guild.text_channels, name=channelNames["tester_logs"])
        if logs_channel is None:
            log.warning(f"[transcript] tester_logs channel '{channelNames['tester_logs']}' not found, skipping transcript upload")
            return

        file_buffer = io.BytesIO(transcript_text.encode("utf-8"))
        file = nextcord.File(fp=file_buffer, filename=f"transcript-{channel.name}.txt")

        await logs_channel.send(
            content=f"📄 Transcript for **#{channel.name}** — closed by {closed_by.mention}",
            file=file
        )
    except Exception:
        log.exception(f"[transcript] Failed to build/post transcript for channel '{channel.name}'")
