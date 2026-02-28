"""Discord bot channel for Jarvis."""

import asyncio
import logging
import os

import discord

logger = logging.getLogger(__name__)


class DiscordBot:
    """Discord bot that forwards messages to Claude Code via the dispatcher."""

    def __init__(self, claude_runner, token: str):
        self.claude_runner = claude_runner
        self.token = token
        self._task: asyncio.Task | None = None

        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)

        # Allowed channel IDs (optional filter)
        allowed = os.getenv("DISCORD_CHANNEL_IDS", "")
        self.allowed_channels: set[int] = set()
        if allowed:
            self.allowed_channels = {int(ch.strip()) for ch in allowed.split(",") if ch.strip()}

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

            # Filter by channel if configured
            if self.allowed_channels and message.channel.id not in self.allowed_channels:
                return

            # Only respond to mentions or DMs
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mention = self.client.user in message.mentions
            if not is_dm and not is_mention:
                return

            # Clean up mention from message
            content = message.content.replace(f"<@{self.client.user.id}>", "").strip()
            if not content:
                return

            session_id = f"discord-{message.author.id}"

            async with message.channel.typing():
                response = await self.claude_runner.send_message(session_id, content)

            # Discord has a 2000 char limit
            if len(response) > 1900:
                chunks = [response[i:i + 1900] for i in range(0, len(response), 1900)]
                for chunk in chunks:
                    await message.reply(chunk)
            else:
                await message.reply(response)

    async def start_background(self):
        """Start the Discord bot in a background task."""
        self._task = asyncio.create_task(self.client.start(self.token))

    async def close(self):
        """Gracefully close the Discord bot."""
        if self.client and not self.client.is_closed():
            await self.client.close()
        if self._task:
            self._task.cancel()
