"""MCP Server for Miniflux (RSS reader).

Provides tools to manage feeds, entries, and categories via Miniflux API v1.
API docs: https://miniflux.app/docs/api.html
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("miniflux")

MINIFLUX_URL = os.getenv("MINIFLUX_URL", "http://miniflux.default.svc.cluster.local:8080")
MINIFLUX_API_KEY = os.getenv("MINIFLUX_API_KEY", "")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=MINIFLUX_URL,
        headers={"X-Auth-Token": MINIFLUX_API_KEY},
        timeout=30,
    )


@mcp.tool()
def list_feeds() -> str:
    """List all RSS feeds with their status."""
    with _client() as client:
        resp = client.get("/v1/feeds")
        resp.raise_for_status()
        feeds = resp.json()
    return json.dumps([{
        "id": f["id"],
        "title": f["title"],
        "site_url": f["site_url"],
        "feed_url": f["feed_url"],
        "category": f.get("category", {}).get("title", ""),
        "parsing_error_count": f.get("parsing_error_count", 0),
        "parsing_error_message": f.get("parsing_error_message", ""),
    } for f in feeds], indent=2)


@mcp.tool()
def list_categories() -> str:
    """List all feed categories."""
    with _client() as client:
        resp = client.get("/v1/categories")
        resp.raise_for_status()
        categories = resp.json()
    return json.dumps([{"id": c["id"], "title": c["title"]} for c in categories], indent=2)


@mcp.tool()
def get_unread_entries(limit: int = 25, category_id: int = 0) -> str:
    """Get unread entries, optionally filtered by category.

    Args:
        limit: Max number of entries to return (default: 25)
        category_id: Filter by category ID (0 for all)
    """
    params = {"status": "unread", "limit": limit, "direction": "desc", "order": "published_at"}
    if category_id:
        params["category_id"] = category_id

    with _client() as client:
        resp = client.get("/v1/entries", params=params)
        resp.raise_for_status()
        data = resp.json()

    entries = data.get("entries", [])
    return json.dumps({
        "total": data.get("total", 0),
        "entries": [{
            "id": e["id"],
            "title": e["title"],
            "url": e["url"],
            "feed": e.get("feed", {}).get("title", ""),
            "author": e.get("author", ""),
            "published_at": e.get("published_at"),
            "reading_time": e.get("reading_time", 0),
        } for e in entries],
    }, indent=2)


@mcp.tool()
def get_entry(entry_id: int) -> str:
    """Get full content of an entry.

    Args:
        entry_id: Entry ID
    """
    with _client() as client:
        resp = client.get(f"/v1/entries/{entry_id}")
        resp.raise_for_status()
        entry = resp.json()
    return json.dumps({
        "id": entry["id"],
        "title": entry["title"],
        "url": entry["url"],
        "author": entry.get("author", ""),
        "content": entry.get("content", ""),
        "published_at": entry.get("published_at"),
        "feed": entry.get("feed", {}).get("title", ""),
        "reading_time": entry.get("reading_time", 0),
        "starred": entry.get("starred", False),
    }, indent=2)


@mcp.tool()
def search_entries(query: str, limit: int = 25) -> str:
    """Search entries by keyword.

    Args:
        query: Search query
        limit: Max results (default: 25)
    """
    with _client() as client:
        resp = client.get("/v1/entries", params={
            "search": query, "limit": limit, "direction": "desc",
        })
        resp.raise_for_status()
        data = resp.json()

    entries = data.get("entries", [])
    return json.dumps({
        "total": data.get("total", 0),
        "entries": [{
            "id": e["id"],
            "title": e["title"],
            "url": e["url"],
            "feed": e.get("feed", {}).get("title", ""),
            "published_at": e.get("published_at"),
            "status": e.get("status"),
        } for e in entries],
    }, indent=2)


@mcp.tool()
def mark_as_read(entry_id: int) -> str:
    """Mark an entry as read.

    Args:
        entry_id: Entry ID
    """
    with _client() as client:
        resp = client.put(f"/v1/entries", json={"entry_ids": [entry_id], "status": "read"})
        resp.raise_for_status()
    return json.dumps({"status": "read", "entry_id": entry_id})


@mcp.tool()
def toggle_star(entry_id: int) -> str:
    """Toggle star/bookmark on an entry.

    Args:
        entry_id: Entry ID
    """
    with _client() as client:
        resp = client.put(f"/v1/entries/{entry_id}/bookmark")
        resp.raise_for_status()
    return json.dumps({"status": "toggled", "entry_id": entry_id})


@mcp.tool()
def get_feed_counters() -> str:
    """Get unread/read counters per feed."""
    with _client() as client:
        resp = client.get("/v1/feeds/counters")
        resp.raise_for_status()
        counters = resp.json()
    reads = counters.get("reads", {})
    unreads = counters.get("unreads", {})
    result = []
    for feed_id in set(list(reads.keys()) + list(unreads.keys())):
        result.append({
            "feed_id": int(feed_id),
            "unread": unreads.get(str(feed_id), 0),
            "read": reads.get(str(feed_id), 0),
        })
    result.sort(key=lambda x: x["unread"], reverse=True)
    return json.dumps(result, indent=2)


@mcp.tool()
def refresh_all_feeds() -> str:
    """Trigger a refresh of all feeds."""
    with _client() as client:
        resp = client.put("/v1/feeds/refresh")
        resp.raise_for_status()
    return json.dumps({"status": "refresh triggered"})


if __name__ == "__main__":
    mcp.run(transport="stdio")
