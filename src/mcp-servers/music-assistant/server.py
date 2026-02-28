"""MCP Server for Music Assistant.

Provides tools to browse music library, control playback, and manage playlists
via Music Assistant REST API.
API docs: https://music-assistant.io/integration/api/
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("music-assistant")

MA_URL = os.getenv("MUSIC_ASSISTANT_URL", "http://music-assistant.default.svc.cluster.local:8095")


def _client() -> httpx.Client:
    return httpx.Client(base_url=MA_URL, timeout=30)


def _api_call(method: str, params: dict = None) -> dict:
    """Call Music Assistant JSON-RPC API."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params

    with _client() as client:
        resp = client.post("/api", json=payload)
        resp.raise_for_status()
        data = resp.json()

    if "error" in data:
        raise Exception(data["error"].get("message", "Unknown error"))
    return data.get("result", {})


@mcp.tool()
def list_players() -> str:
    """List all available music players and their state."""
    result = _api_call("players")
    players = []
    for p in result if isinstance(result, list) else []:
        players.append({
            "player_id": p.get("player_id"),
            "name": p.get("display_name", p.get("name", "")),
            "state": p.get("state", ""),
            "volume": p.get("volume_level"),
            "available": p.get("available", False),
            "current_media": p.get("current_media", {}).get("title", "") if p.get("current_media") else "",
        })
    return json.dumps(players, indent=2)


@mcp.tool()
def get_player(player_id: str) -> str:
    """Get detailed state of a specific player.

    Args:
        player_id: Player ID
    """
    result = _api_call("players")
    players = result if isinstance(result, list) else []
    player = next((p for p in players if p.get("player_id") == player_id), None)
    if not player:
        return f"Player not found: {player_id}"
    return json.dumps(player, indent=2, default=str)


@mcp.tool()
def search(query: str, media_type: str = "", limit: int = 20) -> str:
    """Search the music library.

    Args:
        query: Search text (artist, album, track name)
        media_type: Filter by type: "artist", "album", "track", "playlist", "radio" (empty for all)
        limit: Max results (default: 20)
    """
    params = {"search_query": query, "limit": limit}
    if media_type:
        params["media_type"] = media_type

    result = _api_call("music/search", params)
    output = {}
    for key in ["artists", "albums", "tracks", "playlists", "radio"]:
        items = result.get(key, [])
        if items:
            output[key] = [{
                "item_id": i.get("item_id"),
                "name": i.get("name", ""),
                "provider": i.get("provider", ""),
            } for i in items[:limit]]
    return json.dumps(output, indent=2)


@mcp.tool()
def list_artists(limit: int = 50) -> str:
    """List artists in the library.

    Args:
        limit: Max results (default: 50)
    """
    result = _api_call("music/artists", {"limit": limit, "order_by": "name"})
    items = result.get("items", result) if isinstance(result, dict) else result
    if not isinstance(items, list):
        items = []
    return json.dumps([{
        "item_id": a.get("item_id"),
        "name": a.get("name", ""),
    } for a in items], indent=2)


@mcp.tool()
def list_albums(limit: int = 50) -> str:
    """List albums in the library.

    Args:
        limit: Max results (default: 50)
    """
    result = _api_call("music/albums", {"limit": limit, "order_by": "name"})
    items = result.get("items", result) if isinstance(result, dict) else result
    if not isinstance(items, list):
        items = []
    return json.dumps([{
        "item_id": a.get("item_id"),
        "name": a.get("name", ""),
        "artist": a.get("artists", [{}])[0].get("name", "") if a.get("artists") else "",
        "year": a.get("year"),
    } for a in items], indent=2)


@mcp.tool()
def list_playlists() -> str:
    """List all playlists."""
    result = _api_call("music/playlists")
    items = result.get("items", result) if isinstance(result, dict) else result
    if not isinstance(items, list):
        items = []
    return json.dumps([{
        "item_id": p.get("item_id"),
        "name": p.get("name", ""),
        "owner": p.get("owner", ""),
        "is_editable": p.get("is_editable", False),
    } for p in items], indent=2)


@mcp.tool()
def play_media(player_id: str, media_type: str, item_id: str, queue_option: str = "replace") -> str:
    """Play media on a player.

    Args:
        player_id: Target player ID
        media_type: Type: "track", "album", "artist", "playlist", "radio"
        item_id: Media item ID
        queue_option: "replace" (default), "add", "next", "replace_next"
    """
    result = _api_call("players/play_media", {
        "player_id": player_id,
        "media_type": media_type,
        "item_id": item_id,
        "queue_option": queue_option,
    })
    return json.dumps({"status": "playing", "player_id": player_id, "media": item_id})


@mcp.tool()
def player_command(player_id: str, command: str) -> str:
    """Send a playback command to a player.

    Args:
        player_id: Player ID
        command: Command: "play", "pause", "stop", "next", "previous"
    """
    method_map = {
        "play": "players/play",
        "pause": "players/pause",
        "stop": "players/stop",
        "next": "players/next",
        "previous": "players/previous",
    }
    method = method_map.get(command)
    if not method:
        return f"Unknown command: {command}. Use: play, pause, stop, next, previous"

    _api_call(method, {"player_id": player_id})
    return json.dumps({"status": command, "player_id": player_id})


@mcp.tool()
def set_volume(player_id: str, volume: int) -> str:
    """Set player volume.

    Args:
        player_id: Player ID
        volume: Volume level (0-100)
    """
    _api_call("players/set_volume", {"player_id": player_id, "volume_level": max(0, min(100, volume))})
    return json.dumps({"status": "volume_set", "player_id": player_id, "volume": volume})


@mcp.tool()
def get_queue(player_id: str) -> str:
    """Get the current playback queue of a player.

    Args:
        player_id: Player ID
    """
    result = _api_call("players/get_queue", {"player_id": player_id})
    items = result.get("items", []) if isinstance(result, dict) else []
    current = result.get("current_index", 0) if isinstance(result, dict) else 0
    return json.dumps({
        "current_index": current,
        "items": [{
            "name": i.get("name", ""),
            "artist": i.get("artists", [{}])[0].get("name", "") if i.get("artists") else "",
            "duration": i.get("duration"),
        } for i in items[:30]],
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
