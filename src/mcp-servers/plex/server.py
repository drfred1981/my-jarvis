"""MCP Server for Plex Media Server.

Provides tools to interact with Plex via its REST API:
- List libraries and media content
- See active playback sessions
- Search media
- Get recently added content
- Server status and info

Requires env vars:
  PLEX_URL=http://plex.local:32400
  PLEX_TOKEN=your-plex-token
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("plex")

PLEX_URL = os.getenv("PLEX_URL", "").rstrip("/")
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "")


def _headers() -> dict:
    return {
        "X-Plex-Token": PLEX_TOKEN,
        "Accept": "application/json",
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=PLEX_URL, headers=_headers(), timeout=30)


def _media_summary(item: dict) -> dict:
    """Extract a clean summary from a Plex media item."""
    result = {
        "title": item.get("title", ""),
        "type": item.get("type", ""),
        "year": item.get("year"),
    }
    if item.get("grandparentTitle"):
        result["show"] = item["grandparentTitle"]
    if item.get("parentTitle"):
        result["season"] = item["parentTitle"]
    if item.get("index") is not None:
        result["episode"] = item["index"]
    if item.get("rating"):
        result["rating"] = item["rating"]
    if item.get("duration"):
        result["duration_min"] = round(item["duration"] / 60000, 1)
    if item.get("addedAt"):
        result["added_at"] = item["addedAt"]
    if item.get("ratingKey"):
        result["key"] = item["ratingKey"]
    return result


@mcp.tool()
def get_server_info() -> str:
    """Get Plex server information (version, platform, transcoder status)."""
    with _client() as client:
        resp = client.get("/")
        resp.raise_for_status()
        data = resp.json()

    container = data.get("MediaContainer", {})
    return json.dumps({
        "name": container.get("friendlyName"),
        "version": container.get("version"),
        "platform": container.get("platform"),
        "platform_version": container.get("platformVersion"),
        "transcoder_active": container.get("transcoderActiveVideoSessions", 0),
        "myPlex": container.get("myPlex", False),
    }, indent=2)


@mcp.tool()
def list_libraries() -> str:
    """List all Plex media libraries (movies, TV shows, music, etc.)."""
    with _client() as client:
        resp = client.get("/library/sections")
        resp.raise_for_status()
        data = resp.json()

    libraries = []
    for lib in data.get("MediaContainer", {}).get("Directory", []):
        libraries.append({
            "id": lib.get("key"),
            "title": lib.get("title"),
            "type": lib.get("type"),
            "agent": lib.get("agent"),
            "scanner": lib.get("scanner"),
            "language": lib.get("language"),
        })
    return json.dumps(libraries, indent=2)


@mcp.tool()
def get_library_content(library_id: str, sort: str = "titleSort", limit: int = 50) -> str:
    """Get content from a specific library.

    Args:
        library_id: Library ID (from list_libraries)
        sort: Sort field (titleSort, addedAt, year, rating). Prefix with - for descending.
        limit: Max items to return (default: 50)
    """
    with _client() as client:
        resp = client.get(
            f"/library/sections/{library_id}/all",
            params={
                "sort": sort,
                "X-Plex-Container-Start": 0,
                "X-Plex-Container-Size": limit,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    container = data.get("MediaContainer", {})
    items = [_media_summary(m) for m in container.get("Metadata", [])]
    return json.dumps({
        "library": container.get("title1", ""),
        "total": container.get("totalSize", len(items)),
        "showing": len(items),
        "items": items,
    }, indent=2)


@mcp.tool()
def get_active_sessions() -> str:
    """Get currently active playback sessions (who's watching what)."""
    with _client() as client:
        resp = client.get("/status/sessions")
        resp.raise_for_status()
        data = resp.json()

    container = data.get("MediaContainer", {})
    sessions = []
    for s in container.get("Metadata", []):
        session = _media_summary(s)
        # Add playback info
        if s.get("User"):
            session["user"] = s["User"].get("title", "")
        elif s.get("userThumb"):
            session["user"] = "unknown"
        if s.get("Player"):
            player = s["Player"]
            session["player"] = player.get("title", "")
            session["player_state"] = player.get("state", "")
            session["player_platform"] = player.get("platform", "")
        if s.get("Session"):
            sess = s["Session"]
            session["bandwidth_kbps"] = sess.get("bandwidth", 0)
        if s.get("viewOffset") and s.get("duration"):
            session["progress_percent"] = round(s["viewOffset"] / s["duration"] * 100, 1)
        if s.get("TranscodeSession"):
            tc = s["TranscodeSession"]
            session["transcoding"] = True
            session["transcode_speed"] = tc.get("speed")
            session["video_decision"] = tc.get("videoDecision", "")
        else:
            session["transcoding"] = False
        sessions.append(session)

    return json.dumps({
        "active_sessions": len(sessions),
        "sessions": sessions,
    }, indent=2)


@mcp.tool()
def search(query: str, limit: int = 20) -> str:
    """Search across all Plex libraries.

    Args:
        query: Search text
        limit: Max results (default: 20)
    """
    with _client() as client:
        resp = client.get(
            "/hubs/search",
            params={"query": query, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for hub in data.get("MediaContainer", {}).get("Hub", []):
        hub_type = hub.get("type", "")
        for item in hub.get("Metadata", []):
            entry = _media_summary(item)
            entry["category"] = hub_type
            results.append(entry)

    return json.dumps({
        "query": query,
        "count": len(results),
        "results": results,
    }, indent=2)


@mcp.tool()
def get_recently_added(limit: int = 20) -> str:
    """Get recently added media across all libraries.

    Args:
        limit: Max items to return (default: 20)
    """
    with _client() as client:
        resp = client.get(
            "/library/recentlyAdded",
            params={"X-Plex-Container-Size": limit},
        )
        resp.raise_for_status()
        data = resp.json()

    items = [_media_summary(m) for m in data.get("MediaContainer", {}).get("Metadata", [])]
    return json.dumps({
        "count": len(items),
        "items": items,
    }, indent=2)


@mcp.tool()
def get_on_deck(limit: int = 20) -> str:
    """Get on-deck items (continue watching).

    Args:
        limit: Max items to return (default: 20)
    """
    with _client() as client:
        resp = client.get(
            "/library/onDeck",
            params={"X-Plex-Container-Size": limit},
        )
        resp.raise_for_status()
        data = resp.json()

    items = []
    for m in data.get("MediaContainer", {}).get("Metadata", []):
        item = _media_summary(m)
        if m.get("viewOffset") and m.get("duration"):
            item["progress_percent"] = round(m["viewOffset"] / m["duration"] * 100, 1)
        items.append(item)

    return json.dumps({
        "count": len(items),
        "items": items,
    }, indent=2)


@mcp.tool()
def get_library_stats() -> str:
    """Get statistics for all libraries (item counts, sizes)."""
    with _client() as client:
        resp = client.get("/library/sections")
        resp.raise_for_status()
        data = resp.json()

    stats = []
    for lib in data.get("MediaContainer", {}).get("Directory", []):
        lib_id = lib.get("key")
        lib_stat = {
            "id": lib_id,
            "title": lib.get("title"),
            "type": lib.get("type"),
        }
        # Get item count
        try:
            resp2 = client.get(f"/library/sections/{lib_id}/all", params={"X-Plex-Container-Size": 0})
            resp2.raise_for_status()
            container = resp2.json().get("MediaContainer", {})
            lib_stat["total_items"] = container.get("totalSize", 0)
        except Exception:
            lib_stat["total_items"] = "unknown"
        stats.append(lib_stat)

    return json.dumps(stats, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
