"""Multi-channel notification dispatcher.

Sends proactive messages to all configured channels:
Discord, Web UI (WebSocket), Synology Chat.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class Notifier:
    """Pushes messages to all active communication channels."""

    def __init__(self):
        self._discord_bot = None
        self._ws_manager = None
        self._synology_webhook_url = os.getenv("SYNOLOGY_CHAT_WEBHOOK_URL")

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
                results.append("discord:ok")
            except Exception as e:
                logger.error("Discord notification failed: %s", e)
                results.append("discord:error")

        # WebSocket (all connected clients)
        if self._ws_manager:
            try:
                await self._notify_websocket(message)
                results.append("ws:ok")
            except Exception as e:
                logger.error("WebSocket notification failed: %s", e)
                results.append("ws:error")

        # Synology Chat
        if self._synology_webhook_url:
            try:
                await self._notify_synology(message)
                results.append("synology:ok")
            except Exception as e:
                logger.error("Synology notification failed: %s", e)
                results.append("synology:error")

        logger.info("Notification sent: %s", ", ".join(results) or "no channels")

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
                    # Discord 2000 char limit
                    if len(message) > 1900:
                        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
                        for chunk in chunks:
                            await channel.send(chunk)
                    else:
                        await channel.send(message)

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
