"""MCP Server for Mattermost.

Provides tools to read and post to Mattermost channels, threads, and DMs.

Required env vars:
  MATTERMOST_URL   — Mattermost base URL (e.g. https://mattermost.example.com)
  MATTERMOST_TOKEN — Personal access token or bot token

Optional:
  MATTERMOST_DEFAULT_TEAM_ID — Default team ID to scope channel searches
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("mattermost")

MATTERMOST_URL = os.getenv("MATTERMOST_URL", "").rstrip("/")
MATTERMOST_TOKEN = os.getenv("MATTERMOST_TOKEN", "")
MATTERMOST_DEFAULT_TEAM_ID = os.getenv("MATTERMOST_DEFAULT_TEAM_ID", "")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=MATTERMOST_URL + "/api/v4",
        headers={
            "Authorization": "Bearer " + MATTERMOST_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=30,
    )


def _fmt_post(p: dict) -> dict:
    """Extract the relevant fields from a raw post object."""
    return {
        "id": p.get("id"),
        "create_at": p.get("create_at"),
        "user_id": p.get("user_id"),
        "channel_id": p.get("channel_id"),
        "root_id": p.get("root_id") or None,
        "message": p.get("message"),
        "type": p.get("type") or "regular",
        "file_ids": p.get("file_ids") or [],
    }


# ── Identity ──────────────────────────────────────────────────────────────────

@mcp.tool()
def get_me() -> str:
    """Get current bot/user identity and roles."""
    with _client() as c:
        r = c.get("/users/me")
        r.raise_for_status()
    u = r.json()
    return json.dumps({
        "id": u.get("id"),
        "username": u.get("username"),
        "email": u.get("email"),
        "first_name": u.get("first_name"),
        "last_name": u.get("last_name"),
        "roles": u.get("roles"),
        "is_bot": u.get("is_bot", False),
    }, indent=2)


# ── Teams ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_teams() -> str:
    """List all teams the current user is a member of."""
    with _client() as c:
        r = c.get("/users/me/teams")
        r.raise_for_status()
    teams = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "display_name": t.get("display_name"),
            "type": t.get("type"),
            "description": t.get("description"),
        }
        for t in r.json()
    ]
    return json.dumps({"count": len(teams), "teams": teams}, indent=2)


# ── Channels ─────────────────────────────────────────────────────────────────

@mcp.tool()
def list_channels(team_id: str = "", page: int = 0, per_page: int = 50) -> str:
    """List public channels in a team.

    Args:
        team_id: Team ID (uses MATTERMOST_DEFAULT_TEAM_ID if empty)
        page: Page index (0-based)
        per_page: Channels per page (max 200)
    """
    tid = team_id or MATTERMOST_DEFAULT_TEAM_ID
    with _client() as c:
        r = c.get(f"/teams/{tid}/channels", params={"page": page, "per_page": per_page})
        r.raise_for_status()
    channels = [
        {
            "id": ch.get("id"),
            "name": ch.get("name"),
            "display_name": ch.get("display_name"),
            "type": ch.get("type"),
            "purpose": ch.get("purpose"),
            "header": ch.get("header"),
            "total_msg_count": ch.get("total_msg_count"),
        }
        for ch in r.json()
    ]
    return json.dumps({"team_id": tid, "page": page, "count": len(channels), "channels": channels}, indent=2)


@mcp.tool()
def list_my_channels(team_id: str = "") -> str:
    """List channels the current user is a member of (includes private channels).

    Args:
        team_id: Team ID (uses MATTERMOST_DEFAULT_TEAM_ID if empty)
    """
    tid = team_id or MATTERMOST_DEFAULT_TEAM_ID
    with _client() as c:
        r = c.get(f"/users/me/teams/{tid}/channels")
        r.raise_for_status()
    channels = [
        {
            "id": ch.get("id"),
            "name": ch.get("name"),
            "display_name": ch.get("display_name"),
            "type": ch.get("type"),
            "purpose": ch.get("purpose"),
        }
        for ch in r.json()
    ]
    return json.dumps({"team_id": tid, "count": len(channels), "channels": channels}, indent=2)


@mcp.tool()
def get_channel(channel_id: str) -> str:
    """Get channel details by ID.

    Args:
        channel_id: Mattermost channel ID
    """
    with _client() as c:
        r = c.get(f"/channels/{channel_id}")
        r.raise_for_status()
    ch = r.json()
    return json.dumps({
        "id": ch.get("id"),
        "name": ch.get("name"),
        "display_name": ch.get("display_name"),
        "type": ch.get("type"),
        "team_id": ch.get("team_id"),
        "purpose": ch.get("purpose"),
        "header": ch.get("header"),
        "total_msg_count": ch.get("total_msg_count"),
        "creator_id": ch.get("creator_id"),
    }, indent=2)


@mcp.tool()
def get_channel_by_name(channel_name: str, team_id: str = "") -> str:
    """Get a channel by team name + channel name.

    Args:
        channel_name: Channel name (URL-safe, e.g. "town-square")
        team_id: Team ID (uses MATTERMOST_DEFAULT_TEAM_ID if empty)
    """
    tid = team_id or MATTERMOST_DEFAULT_TEAM_ID
    with _client() as c:
        r = c.get(f"/teams/{tid}/channels/name/{channel_name}")
        r.raise_for_status()
    ch = r.json()
    return json.dumps({
        "id": ch.get("id"),
        "name": ch.get("name"),
        "display_name": ch.get("display_name"),
        "type": ch.get("type"),
        "team_id": ch.get("team_id"),
        "total_msg_count": ch.get("total_msg_count"),
    }, indent=2)


# ── Posts (read) ──────────────────────────────────────────────────────────────

@mcp.tool()
def get_posts(channel_id: str, page: int = 0, per_page: int = 30) -> str:
    """Get recent posts in a channel, newest first.

    Args:
        channel_id: Channel ID
        page: Page index (0-based, 0 = most recent)
        per_page: Posts per page (max 200)
    """
    with _client() as c:
        r = c.get(f"/channels/{channel_id}/posts", params={"page": page, "per_page": per_page})
        r.raise_for_status()
    data = r.json()
    order = data.get("order", [])
    posts_map = data.get("posts", {})
    posts = [_fmt_post(posts_map[pid]) for pid in order if pid in posts_map]
    return json.dumps({"channel_id": channel_id, "count": len(posts), "posts": posts}, indent=2)


@mcp.tool()
def get_thread(post_id: str) -> str:
    """Get a full thread (root post + all replies) by root post ID.

    Args:
        post_id: Root post ID
    """
    with _client() as c:
        r = c.get(f"/posts/{post_id}/thread")
        r.raise_for_status()
    data = r.json()
    order = data.get("order", [])
    posts_map = data.get("posts", {})
    posts = [_fmt_post(posts_map[pid]) for pid in order if pid in posts_map]
    return json.dumps({"root_post_id": post_id, "count": len(posts), "posts": posts}, indent=2)


@mcp.tool()
def get_post(post_id: str) -> str:
    """Get a single post by ID.

    Args:
        post_id: Post ID
    """
    with _client() as c:
        r = c.get(f"/posts/{post_id}")
        r.raise_for_status()
    return json.dumps(_fmt_post(r.json()), indent=2)


# ── Posts (write) ─────────────────────────────────────────────────────────────

@mcp.tool()
def post_message(channel_id: str, message: str, root_id: str = "") -> str:
    """Post a message to a channel, or reply to a thread.

    Args:
        channel_id: Channel ID to post in
        message: Message text (Markdown supported)
        root_id: Root post ID to reply to (empty = new post, not a thread reply)
    """
    body: dict = {"channel_id": channel_id, "message": message}
    if root_id:
        body["root_id"] = root_id
    with _client() as c:
        r = c.post("/posts", json=body)
        r.raise_for_status()
    p = r.json()
    return json.dumps({
        "id": p.get("id"),
        "channel_id": p.get("channel_id"),
        "root_id": p.get("root_id") or None,
        "create_at": p.get("create_at"),
        "message": p.get("message"),
    }, indent=2)


# ── Search ────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_posts(terms: str, team_id: str = "", is_or_search: bool = False,
                 page: int = 0, per_page: int = 20) -> str:
    """Full-text search for posts across channels.

    Args:
        terms: Search query (supports Mattermost operators: from:, in:, before:, after:)
        team_id: Scope to a team (uses MATTERMOST_DEFAULT_TEAM_ID if empty)
        is_or_search: If True, match any term; if False (default), match all terms
        page: Result page
        per_page: Results per page (max 200)
    """
    tid = team_id or MATTERMOST_DEFAULT_TEAM_ID
    body = {"terms": terms, "is_or_search": is_or_search, "page": page, "per_page": per_page}
    with _client() as c:
        r = c.post(f"/teams/{tid}/posts/search", json=body)
        r.raise_for_status()
    data = r.json()
    order = data.get("order", [])
    posts_map = data.get("posts", {})
    posts = [_fmt_post(posts_map[pid]) for pid in order if pid in posts_map]
    return json.dumps({"terms": terms, "count": len(posts), "posts": posts}, indent=2)


# ── Users ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_user(user_id: str) -> str:
    """Get a user's profile by ID. Use 'me' for the current user.

    Args:
        user_id: Mattermost user ID, or 'me'
    """
    with _client() as c:
        r = c.get(f"/users/{user_id}")
        r.raise_for_status()
    u = r.json()
    return json.dumps({
        "id": u.get("id"),
        "username": u.get("username"),
        "email": u.get("email"),
        "first_name": u.get("first_name"),
        "last_name": u.get("last_name"),
        "nickname": u.get("nickname"),
        "roles": u.get("roles"),
        "is_bot": u.get("is_bot", False),
        "last_activity_at": u.get("last_activity_at"),
    }, indent=2)


@mcp.tool()
def get_user_by_username(username: str) -> str:
    """Get a user's profile by username.

    Args:
        username: Mattermost username (without @)
    """
    with _client() as c:
        r = c.get(f"/users/username/{username}")
        r.raise_for_status()
    u = r.json()
    return json.dumps({
        "id": u.get("id"),
        "username": u.get("username"),
        "email": u.get("email"),
        "first_name": u.get("first_name"),
        "last_name": u.get("last_name"),
        "nickname": u.get("nickname"),
        "roles": u.get("roles"),
    }, indent=2)


@mcp.tool()
def search_users(term: str, team_id: str = "", limit: int = 25) -> str:
    """Search for users by username, email, first/last name.

    Args:
        term: Search term
        team_id: Scope to a team (uses MATTERMOST_DEFAULT_TEAM_ID if empty)
        limit: Max results (default 25)
    """
    tid = team_id or MATTERMOST_DEFAULT_TEAM_ID
    body: dict = {"term": term, "limit": limit}
    if tid:
        body["team_id"] = tid
    with _client() as c:
        r = c.post("/users/search", json=body)
        r.raise_for_status()
    users = [
        {
            "id": u.get("id"),
            "username": u.get("username"),
            "first_name": u.get("first_name"),
            "last_name": u.get("last_name"),
            "nickname": u.get("nickname"),
            "email": u.get("email"),
        }
        for u in r.json()
    ]
    return json.dumps({"term": term, "count": len(users), "users": users}, indent=2)


# ── Direct Messages ───────────────────────────────────────────────────────────

@mcp.tool()
def create_direct_channel(user_id: str) -> str:
    """Create or get the DM channel between the bot and a user.

    Returns the channel ID to use with post_message/get_posts.

    Args:
        user_id: Target user ID
    """
    with _client() as c:
        me_r = c.get("/users/me")
        me_r.raise_for_status()
        my_id = me_r.json()["id"]
        r = c.post("/channels/direct", json=[my_id, user_id])
        r.raise_for_status()
    ch = r.json()
    return json.dumps({
        "channel_id": ch.get("id"),
        "name": ch.get("name"),
        "type": ch.get("type"),
    }, indent=2)


# ── File info ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_file_info(file_id: str) -> str:
    """Get metadata for a file attachment.

    Args:
        file_id: File ID (from a post's file_ids list)
    """
    with _client() as c:
        r = c.get(f"/files/{file_id}/info")
        r.raise_for_status()
    f = r.json()
    return json.dumps({
        "id": f.get("id"),
        "name": f.get("name"),
        "size": f.get("size"),
        "mime_type": f.get("mime_type"),
        "extension": f.get("extension"),
        "has_preview_image": f.get("has_preview_image"),
        "creator_id": f.get("user_id"),
        "create_at": f.get("create_at"),
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
