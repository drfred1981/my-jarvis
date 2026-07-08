"""MCP Server for discord-write — let the agent create threads and post messages.

Used mainly to give each managed repo its own dedicated thread (see the
`repo-workflow` skill): the agent creates a thread, records the repo↔thread
binding in that conversation's local context, and works the repo there.

Thin wiring over `api` (Discord REST). Requires env: DISCORD_BOT_TOKEN
(the bot must be in the target guild with Manage Threads / Send Messages).
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

import api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("discord-write")


def _j(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def create_thread(channel_id: str, name: str, private: bool = False,
                  auto_archive_minutes: int = 1440) -> str:
    """Create a thread in a parent text channel (e.g. one per managed repo).

    Returns the new `thread_id` and the `conversation_key` (`discord:thread:<id>`)
    to use for that conversation. `auto_archive_minutes` ∈ {60, 1440, 4320, 10080}.
    """
    return _j(api.create_thread(channel_id, name, private, auto_archive_minutes))


@mcp.tool()
def post_message(channel_id: str, content: str) -> str:
    """Post a message to a channel or thread (a thread id works as channel_id).
    Long content is split into Discord-safe chunks."""
    return _j(api.post_message(channel_id, content))


@mcp.tool()
def post_file(channel_id: str, file_path: str, content: str = "") -> str:
    """Publish a local file as an attachment to a channel or thread (a thread id
    works as channel_id), with optional message text.

    Use to send a generated artefact to Discord — a report, export, log, diagram,
    image, CSV… Write the file first (e.g. under `/home/jarvis`), then pass its path.
    `file_path` must be readable by Jarvis; max 25 MiB by default. Returns the
    message id and the uploaded attachment URL(s)."""
    return _j(api.post_file(channel_id, file_path, content))


@mcp.tool()
def list_active_threads(guild_id: str) -> str:
    """List active threads in a guild — to find an existing repo thread before
    creating a new one."""
    return _j(api.list_active_threads(guild_id))


if __name__ == "__main__":
    mcp.run()
