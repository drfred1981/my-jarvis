"""Discord bot channel for Jarvis."""

import asyncio
import logging
import os

import discord

from conversations import channel_config, keys
from metrics import MESSAGES_TOTAL, MESSAGE_DURATION_SECONDS

logger = logging.getLogger(__name__)

# Explicit invocation prefix for multi-user channels.
INVOCATION_PREFIX = os.getenv("DISCORD_INVOCATION_PREFIX", "/claude")

# How many recent channel messages to feed as context in multi-user channels.
HISTORY_LIMIT = int(os.getenv("DISCORD_HISTORY_LIMIT", "15"))

# Where incoming Discord attachments are saved so Jarvis can read/analyze them.
# Under the claude cwd (/home/jarvis) → reachable by the agent's Read/Bash tools.
INBOX_DIR = os.getenv("JARVIS_DISCORD_INBOX", "/home/jarvis/discord-inbox")
# Skip downloading attachments larger than this (Jarvis analyzes files, not blobs).
MAX_ATTACHMENT_BYTES = int(os.getenv("DISCORD_MAX_ATTACHMENT_MB", "25")) * 1024 * 1024


def safe_attachment_name(name: str) -> str:
    """Reduce an attachment filename to a safe basename (no path traversal).

    Discord filenames are usually benign, but never trust one to build a path:
    strip any directory part and leading dots, keep a conservative charset.
    """
    base = os.path.basename(name or "").strip().lstrip(".")
    cleaned = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in base)
    return cleaned.strip() or "file"


def parse_invocation(content: str, mentioned: bool) -> tuple[bool, str]:
    """In a multi-user channel, the agent only acts when explicitly invoked.

    Returns (invoked, cleaned_content). Invocation = an @mention (already stripped
    from content) or the ``/claude`` prefix.
    """
    if mentioned:
        return True, content
    if content.startswith(INVOCATION_PREFIX):
        return True, content[len(INVOCATION_PREFIX):].strip()
    return False, content


class DiscordBot:
    """Discord bot that forwards messages to Claude Code via the dispatcher."""

    def __init__(self, claude_runner, token: str):
        self.claude_runner = claude_runner
        self.token = token
        self._task: asyncio.Task | None = None

        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)

        # Allowed channel IDs (optional filter). Accepts the structured JSON form
        # ([{"id","description"}]) or the legacy comma-separated list.
        self.allowed_channels: set[int] = channel_config.channel_ids(
            os.getenv("DISCORD_CHANNEL_IDS", ""))

        self._register_handlers()

    def _register_handlers(self):
        @self.client.event
        async def on_ready():
            logger.info("Discord bot logged in as %s", self.client.user)

        @self.client.event
        async def on_message(message: discord.Message):
            # Ignore own messages
            if message.author == self.client.user:
                return

            logger.info("Discord message from %s in #%s: %s",
                        message.author, getattr(message.channel, 'name', 'DM'), message.content[:100])

            is_dm = isinstance(message.channel, discord.DMChannel)

            # Allowlist gate (DMs always allowed).
            if self.allowed_channels and not is_dm and message.channel.id not in self.allowed_channels:
                logger.debug("Ignored: channel %s not in allowed list", message.channel.id)
                return

            mode, session_id = self._resolve_conversation(message, is_dm)

            # Strip the bot mention from the content.
            content = message.content.replace(f"<@{self.client.user.id}>", "").strip()
            mentioned = self.client.user in message.mentions

            # Multi-user channels: act only when explicitly invoked (/claude or @mention).
            if mode == "multiuser":
                invoked, content = parse_invocation(content, mentioned)
                if not invoked:
                    logger.debug("Multi-user channel, not invoked → reading only")
                    return

            # Download any attachments so Jarvis can analyze them locally, and note
            # their paths in the prompt. Done only for messages we actually process.
            attach_note = await self._download_attachments(message)

            if not content and not attach_note:
                return

            # Fold the attachment note into the user's message.
            user_msg = f"{content}\n\n{attach_note}".strip() if attach_note else content

            # Persist the mode, then build the prompt (multi-user → recent history).
            self.claude_runner.registry.get_or_create(session_id, mode=mode)
            self.claude_runner.registry.set_mode(session_id, mode)
            prompt = user_msg
            if mode == "multiuser":
                history = await self._recent_history(message.channel)
                if history:
                    prompt = f"{history}\n\n---\n\nMessage adressé à toi :\n{user_msg}"

            logger.info("Discord → Claude (session=%s, mode=%s)", session_id, mode)
            status_msg = None

            async def heartbeat(elapsed):
                nonlocal status_msg
                txt = f"⏳ Je travaille toujours… ({int(elapsed)}s)"
                try:
                    if status_msg is None:
                        status_msg = await message.channel.send(txt)
                    else:
                        await status_msg.edit(content=txt)
                except Exception:
                    pass

            try:
                async with message.channel.typing():
                    with MESSAGE_DURATION_SECONDS.labels(channel="discord").time():
                        response = await self.claude_runner.send_message(
                            session_id, prompt, is_user_initiated=True, heartbeat=heartbeat)
                    logger.info("Claude response (session=%s, len=%d): %s",
                                session_id, len(response), response[:200])

                if status_msg is not None:
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass

                MESSAGES_TOTAL.labels(channel="discord", status="success").inc()

                for chunk in self._chunks(response):
                    await message.reply(chunk)
                logger.info("Discord reply sent to %s", message.author)

            except Exception as e:
                MESSAGES_TOTAL.labels(channel="discord", status="error").inc()
                logger.error("Discord message handling failed: %s", e, exc_info=True)
                try:
                    await message.reply(f"Erreur: {e}")
                except Exception:
                    pass

    def _resolve_conversation(self, message, is_dm: bool) -> tuple[str, str]:
        """Return (mode, conversation_key) for a Discord message.

        - DM → direct.
        - channel explicitly in DISCORD_CHANNEL_IDS → direct (always-on opt-in).
        - group DM with ≤2 humans → direct; otherwise → multiuser.
        - guild channel / thread → multiuser (invoke-only).
        """
        if is_dm:
            return "direct", keys.discord_dm(message.author.id)

        if isinstance(message.channel, discord.Thread):
            return "multiuser", keys.discord_thread(message.channel.id)

        if isinstance(message.channel, discord.GroupChannel):
            humans = [r for r in getattr(message.channel, "recipients", []) if not r.bot]
            mode = "direct" if len(humans) <= 2 else "multiuser"
            return mode, keys.discord_channel(message.channel.id)

        # Guild text channel
        if self.allowed_channels and message.channel.id in self.allowed_channels:
            return "direct", keys.discord_channel(message.channel.id)
        return "multiuser", keys.discord_channel(message.channel.id)

    async def _download_attachments(self, message) -> str:
        """Save a message's attachments locally and return a note listing their paths.

        Files land under ``INBOX_DIR/<message_id>/`` (below the agent's cwd) so Jarvis
        can Read/analyze them. Returns "" when there is nothing to surface. Oversized
        or failed items are reported in the note rather than silently dropped.
        """
        attachments = getattr(message, "attachments", None)
        if not attachments:
            return ""
        base = os.path.join(INBOX_DIR, str(message.id))
        lines = []
        for att in attachments:
            name = safe_attachment_name(att.filename)
            if att.size and att.size > MAX_ATTACHMENT_BYTES:
                lines.append(f"- {name} — non récupéré (trop volumineux : "
                             f"{att.size // (1024 * 1024)} Mo)")
                continue
            dest = os.path.join(base, name)
            try:
                os.makedirs(base, exist_ok=True)
                await att.save(dest)
                meta = f" ({att.content_type})" if getattr(att, "content_type", None) else ""
                lines.append(f"- `{dest}`{meta}")
            except Exception as e:
                logger.warning("Discord attachment save failed (%s): %s", name, e)
                lines.append(f"- {name} — échec du téléchargement ({e})")
        if not lines:
            return ""
        return ("Pièces jointes reçues, enregistrées localement (lis-les avec ton outil "
                "`Read` / analyse-les si pertinent) :\n" + "\n".join(lines))

    async def _recent_history(self, channel, limit: int = HISTORY_LIMIT) -> str:
        """Recent channel messages as a context preamble (multi-user channels)."""
        try:
            msgs = [m async for m in channel.history(limit=limit)]
        except Exception as e:
            logger.debug("history fetch failed: %s", e)
            return ""
        lines = [f"{m.author.display_name}: {m.content}"
                 for m in reversed(msgs) if m.content and m.author != self.client.user]
        return "Contexte récent du salon :\n" + "\n".join(lines) if lines else ""

    @staticmethod
    def _chunks(message: str, size: int = 1900):
        """Split into Discord-safe chunks (2000 char hard limit)."""
        return [message[i:i + size] for i in range(0, len(message), size)] or [""]

    async def send_dm(self, user_id, message: str):
        """Send a direct message to a user (used for individual coaching)."""
        user = await self.client.fetch_user(int(user_id))
        for i in range(0, len(message), 1900):
            await user.send(message[i:i + 1900])

    async def start_background(self):
        """Start the Discord bot in a background task."""
        self._task = asyncio.create_task(self.client.start(self.token))

    async def close(self):
        """Gracefully close the Discord bot."""
        if self.client and not self.client.is_closed():
            await self.client.close()
        if self._task:
            self._task.cancel()
