"""Discord REST API client for the discord-write MCP.

MCP servers are short-lived subprocesses of `claude -p`, so opening a gateway
(websocket) connection per call is wasteful. Thread creation and posting are done
directly against the Discord REST API with the bot token.

Base: https://discord.com/api/v10 — auth header ``Authorization: Bot <token>``.

Imported flat (``import api``): the server runs as a script.
Requires env: DISCORD_BOT_TOKEN.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
API = "https://discord.com/api/v10"

# Thread channel types.
PUBLIC_THREAD = 11
PRIVATE_THREAD = 12
# Allowed auto-archive durations (minutes).
_VALID_ARCHIVE = {60, 1440, 4320, 10080}

_CHUNK = 1900  # Discord hard limit is 2000


def _headers() -> dict:
    return {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}


def _request(method: str, path: str, **kw):
    """Return (json_or_dict, None) or (None, error_string)."""
    try:
        resp = httpx.request(method, f"{API}{path}", headers=_headers(), timeout=30, **kw)
    except httpx.HTTPError as e:
        return None, f"Discord API error: {e}"
    if resp.status_code >= 300:
        return None, f"Discord API {resp.status_code}: {resp.text[:300]}"
    return (resp.json() if resp.content else {}), None


def create_thread(channel_id: str, name: str, private: bool = False,
                  auto_archive_minutes: int = 1440) -> dict:
    """Create a thread (not attached to a message) in a parent text channel."""
    if not TOKEN:
        return {"error": "DISCORD_BOT_TOKEN not set"}
    if not name.strip():
        return {"error": "thread name is required"}
    if auto_archive_minutes not in _VALID_ARCHIVE:
        auto_archive_minutes = 1440
    body = {
        "name": name.strip()[:100],
        "type": PRIVATE_THREAD if private else PUBLIC_THREAD,
        "auto_archive_duration": auto_archive_minutes,
    }
    data, err = _request("POST", f"/channels/{channel_id}/threads", json=body)
    if err:
        return {"error": err}
    tid = data.get("id")
    return {"ok": True, "thread_id": str(tid), "name": data.get("name"),
            "parent_id": str(data.get("parent_id")),
            "conversation_key": f"discord:thread:{tid}"}


def post_message(channel_id: str, content: str) -> dict:
    """Post a message to a channel or thread (a thread id is a channel id)."""
    if not TOKEN:
        return {"error": "DISCORD_BOT_TOKEN not set"}
    if not content.strip():
        return {"error": "empty content"}
    sent = []
    for i in range(0, len(content), _CHUNK):
        data, err = _request("POST", f"/channels/{channel_id}/messages",
                             json={"content": content[i:i + _CHUNK]})
        if err:
            return {"error": err, "sent": sent}
        sent.append(str(data.get("id")))
    return {"ok": True, "channel_id": str(channel_id), "messages": sent}


def list_active_threads(guild_id: str) -> dict:
    """List active (non-archived) threads in a guild — find an existing repo thread."""
    if not TOKEN:
        return {"error": "DISCORD_BOT_TOKEN not set"}
    data, err = _request("GET", f"/guilds/{guild_id}/threads/active")
    if err:
        return {"error": err}
    threads = [{"id": str(t.get("id")), "name": t.get("name"),
                "parent_id": str(t.get("parent_id"))}
               for t in data.get("threads", [])]
    return {"ok": True, "threads": threads}
