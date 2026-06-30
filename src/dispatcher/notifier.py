"""Multi-channel notification dispatcher.

Two delivery shapes, matching the conversation-context doctrine:

  - **broadcast** (`notify_all`) : push to every configured channel. Reserve this
    for genuinely global, critical signals — NOT routine monitoring or coaching.
  - **targeted** (`notify_conversation`, `notify_monitoring`, `notify_user`) : push
    to the single destination encoded in a conversation key, so output stays
    cloisonné per conversation (monitoring goes only to its dedicated channel,
    coaching is posted into the conversation it was tailored for).
"""

import logging
import os

import httpx

from conversations import keys
from metrics import NOTIFICATIONS_TOTAL

logger = logging.getLogger(__name__)


class Notifier:
    """Pushes messages to all active communication channels."""

    def __init__(self):
        self._discord_bot = None
        self._ws_manager = None
        self._synology_webhook_url = os.getenv("SYNOLOGY_CHAT_WEBHOOK_URL")
        # Optional dedicated Discord channel for team coaching / proactive posts.
        self._coaching_channel_id = os.getenv("DISCORD_COACHING_CHANNEL_ID", "").strip()
        # Dedicated Discord channel for infra monitoring (Track A). Monitoring is
        # NEVER broadcast into conversation-specific channels — it lives only here.
        self._monitor_channel_id = os.getenv("JARVIS_MONITOR_CHANNEL_ID", "").strip()

    def set_discord_bot(self, bot):
        self._discord_bot = bot

    def set_ws_manager(self, manager):
        self._ws_manager = manager

    async def notify_all(self, message: str):
        """Send a notification to all configured channels."""
        results = []

        # Discord
        if self._discord_bot:
            try:
                await self._notify_discord(message)
                NOTIFICATIONS_TOTAL.labels(channel="discord", status="success").inc()
                results.append("discord:ok")
            except Exception as e:
                NOTIFICATIONS_TOTAL.labels(channel="discord", status="error").inc()
                logger.error("Discord notification failed: %s", e)
                results.append("discord:error")

        # WebSocket (all connected clients)
        if self._ws_manager:
            try:
                await self._notify_websocket(message)
                NOTIFICATIONS_TOTAL.labels(channel="websocket", status="success").inc()
                results.append("ws:ok")
            except Exception as e:
                NOTIFICATIONS_TOTAL.labels(channel="websocket", status="error").inc()
                logger.error("WebSocket notification failed: %s", e)
                results.append("ws:error")

        # Synology Chat
        if self._synology_webhook_url:
            try:
                await self._notify_synology(message)
                NOTIFICATIONS_TOTAL.labels(channel="synology", status="success").inc()
                results.append("synology:ok")
            except Exception as e:
                NOTIFICATIONS_TOTAL.labels(channel="synology", status="error").inc()
                logger.error("Synology notification failed: %s", e)
                results.append("synology:error")

        logger.info("Notification sent: %s", ", ".join(results) or "no channels")

    async def notify_coaching(self, message: str):
        """Post a team-level coaching / perimeter-review message.

        Targets the dedicated coaching channel when `DISCORD_COACHING_CHANNEL_ID`
        is set. If it is NOT set, the message is logged and dropped — it is NEVER
        broadcast into conversation-specific channels (that violated the
        per-conversation isolation doctrine). Per-conversation coaching is
        delivered separately via `notify_conversation`.
        """
        if not await self._post_to_channel(self._coaching_channel_id, message, label="coaching"):
            logger.info(
                "notify_coaching: no DISCORD_COACHING_CHANNEL_ID set, team review "
                "logged only (not broadcast): %s", message[:120])

    async def notify_monitoring(self, message: str):
        """Post infra monitoring (Track A) to its single dedicated channel.

        Never broadcasts into conversation-specific channels. Falls back to the
        coaching channel, then to log-only — but never to `notify_all`.
        """
        target = self._monitor_channel_id or self._coaching_channel_id
        if not await self._post_to_channel(target, message, label="monitoring"):
            logger.info(
                "notify_monitoring: no JARVIS_MONITOR_CHANNEL_ID/"
                "DISCORD_COACHING_CHANNEL_ID set, monitoring logged only "
                "(not broadcast): %s", message[:120])

    async def _post_to_channel(self, channel_id: str, message: str, *, label: str) -> bool:
        """Post to a single Discord channel id. Returns True if delivered."""
        bot = self._discord_bot
        if channel_id and bot and bot.client.is_ready():
            channel = bot.client.get_channel(int(channel_id))
            if channel:
                try:
                    await self._send_chunks(channel, message)
                    NOTIFICATIONS_TOTAL.labels(channel=label, status="success").inc()
                    return True
                except Exception as e:
                    NOTIFICATIONS_TOTAL.labels(channel=label, status="error").inc()
                    logger.error("%s channel notification failed: %s", label, e)
        return False

    async def _send_chunks(self, channel, message: str):
        for chunk in self._chunks(message):
            await channel.send(chunk)

    async def notify_conversation(self, conversation_key: str, message: str):
        """Route a proactive message to the SINGLE destination encoded in the
        conversation key — the per-conversation isolation primitive.

        Discord channel/thread → that channel; Discord DM / Synology → that user;
        web → that WebSocket session. System tracks (introspection, monitor:*) and
        unrecognized keys are skipped (use `notify_monitoring`/`notify_coaching`).
        """
        p = keys.parse(conversation_key)
        try:
            if p.channel == "discord":
                if p.kind == "dm":
                    await self.notify_user(("discord", p.ident), message)
                elif p.kind in ("channel", "thread"):
                    await self._notify_discord_channel(int(p.ident), message)
                else:
                    logger.info("notify_conversation: unroutable discord key %s", conversation_key)
            elif p.channel == "web" and self._ws_manager:
                await self._ws_manager.broadcast(message, p.ident)
            elif p.channel == "synology" and self._synology_webhook_url:
                await self._notify_synology(message)
            else:
                logger.info("notify_conversation: non-routable key %s, skipping", conversation_key)
        except Exception as e:
            logger.error("notify_conversation %s failed: %s", conversation_key, e)

    async def _notify_discord_channel(self, channel_id: int, message: str):
        """Send to one specific Discord channel or thread id (no broadcast)."""
        bot = self._discord_bot
        if not bot or not bot.client.is_ready():
            return
        channel = bot.client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.client.fetch_channel(channel_id)
            except Exception as e:
                logger.warning("notify_conversation: discord channel %s not found: %s",
                               channel_id, e)
                return
        await self._send_chunks(channel, message)

    async def notify_user(self, target: tuple[str, str], message: str):
        """Send an individual (direct) message to a specific user.

        `target` is a (kind, ident) tuple, e.g. ("discord", "123456789").
        Only Discord DMs are supported for now; other kinds are logged and skipped.
        """
        kind, ident = target
        if kind == "discord" and self._discord_bot and self._discord_bot.client.is_ready():
            try:
                await self._discord_bot.send_dm(ident, message)
                NOTIFICATIONS_TOTAL.labels(channel="discord-dm", status="success").inc()
            except Exception as e:
                NOTIFICATIONS_TOTAL.labels(channel="discord-dm", status="error").inc()
                logger.error("Discord DM to %s failed: %s", ident, e)
        else:
            logger.info("notify_user: unsupported/unready target %s, skipping", target)

    @staticmethod
    def _chunks(message: str, size: int = 1900):
        """Split a message into Discord-safe chunks (2000 char hard limit)."""
        return [message[i:i + size] for i in range(0, len(message), size)] or [""]

    async def _notify_discord(self, message: str):
        """Send to Discord via the bot's configured channels."""
        bot = self._discord_bot
        if not bot or not bot.client.is_ready():
            return

        # Send to all allowed channels, or DM the bot owner
        if bot.allowed_channels:
            for channel_id in bot.allowed_channels:
                channel = bot.client.get_channel(channel_id)
                if channel:
                    for chunk in self._chunks(message):
                        await channel.send(chunk)

    async def _notify_websocket(self, message: str):
        """Broadcast to all connected WebSocket clients."""
        for session_id in list(self._ws_manager.active_connections.keys()):
            await self._ws_manager.broadcast(message, session_id)

    async def _notify_synology(self, message: str):
        """Send via Synology Chat incoming webhook."""
        # Strip markdown for Synology Chat (basic text only)
        clean = message.replace("**", "").replace("🔔 ", "")
        payload = f'payload={{"text": "{clean}"}}'
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._synology_webhook_url,
                content=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
