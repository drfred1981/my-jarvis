"""Synology Chat integration for Jarvis.

Synology Chat uses incoming/outgoing webhooks:
- Outgoing webhook: Synology sends messages to our /api/webhooks/synology endpoint
- Incoming webhook: We send responses back via a webhook URL

The outgoing webhook is handled in main.py.
This module provides the helper to send proactive messages via incoming webhook.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


class SynologyChat:
    """Client for sending messages to Synology Chat via incoming webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self._client = httpx.AsyncClient()

    async def send_message(self, text: str) -> bool:
        """Send a message to Synology Chat via incoming webhook."""
        try:
            payload = f'payload={{"text": "{text}"}}'
            resp = await self._client.post(
                self.webhook_url,
                content=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Failed to send Synology Chat message: %s", e)
            return False

    async def close(self):
        await self._client.aclose()
