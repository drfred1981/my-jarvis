"""Multi-channel notification dispatcher.

Sends proactive messages to all configured channels:
Discord, Web UI (WebSocket), Synology Chat.
"""

import logging
import os

import httpx

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
        """Post a team-coaching / proactive message.

        Targets the dedicated coaching channel when `DISCORD_COACHING_CHANNEL_ID`
        is set; otherwise falls back to broadcasting on all channels.
        """
        bot = self._discord_bot
        if self._coaching_channel_id and bot and bot.client.is_ready():
            channel = bot.client.get_channel(int(self._coaching_channel_id))
            if channel:
                try:
                    for chunk in self._chunks(message):
                        await channel.send(chunk)
                    NOTIFICATIONS_TOTAL.labels(channel="coaching", status="success").inc()
                    return
                except Exception as e:
                    NOTIFICATIONS_TOTAL.labels(channel="coaching", status="error").inc()
                    logger.error("Coaching channel notification failed: %s", e)
        # Fallback: broadcast everywhere.
        await self.notify_all(message)

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
