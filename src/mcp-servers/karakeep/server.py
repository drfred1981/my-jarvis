"""MCP Server for Karakeep (bookmark manager, formerly Hoarder).

Provides tools to manage bookmarks, lists, and tags via Karakeep API.
API docs: https://docs.karakeep.app/api/
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("karakeep")

KARAKEEP_URL = os.getenv("KARAKEEP_URL", "http://karakeep.default.svc.cluster.local:3000")
KARAKEEP_API_KEY = os.getenv("KARAKEEP_API_KEY", "")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=KARAKEEP_URL,
        headers={"Authorization": f"Bearer {KARAKEEP_API_KEY}"},
        timeout=30,
    )


@mcp.tool()
def list_bookmarks(limit: int = 25, archived: bool = False, favourited: bool = False) -> str:
    """List bookmarks, optionally filtered.

    Args:
        limit: Max number of bookmarks (default: 25)
        archived: If true, show only archived bookmarks
        favourited: If true, show only favourited bookmarks
    """
    params = {"limit": limit}
    if archived:
        params["archived"] = "true"
    if favourited:
        params["favourited"] = "true"

    with _client() as client:
        resp = client.get("/api/v1/bookmarks", params=params)
        resp.raise_for_status()
        data = resp.json()

    bookmarks = data.get("bookmarks", [])
    return json.dumps([{
        "id": b["id"],
        "title": b.get("title", ""),
        "url": b.get("content", {}).get("url", "") if b.get("content", {}).get("type") == "link" else "",
        "type": b.get("content", {}).get("type", ""),
        "summary": b.get("summary", ""),
        "tags": [t.get("name", "") for t in b.get("tags", [])],
        "favourited": b.get("favourited", False),
        "archived": b.get("archived", False),
        "created_at": b.get("createdAt", ""),
    } for b in bookmarks], indent=2)


@mcp.tool()
def search_bookmarks(query: str, limit: int = 25) -> str:
    """Search bookmarks by text.

    Args:
        query: Search query
        limit: Max results (default: 25)
    """
    with _client() as client:
        resp = client.get("/api/v1/bookmarks/search", params={"q": query, "limit": limit})
        resp.raise_for_status()
        data = resp.json()

    bookmarks = data.get("bookmarks", [])
    return json.dumps([{
        "id": b["id"],
        "title": b.get("title", ""),
        "url": b.get("content", {}).get("url", "") if b.get("content", {}).get("type") == "link" else "",
        "summary": b.get("summary", ""),
        "tags": [t.get("name", "") for t in b.get("tags", [])],
    } for b in bookmarks], indent=2)


@mcp.tool()
def get_bookmark(bookmark_id: str) -> str:
    """Get full details of a bookmark.

    Args:
        bookmark_id: Bookmark ID
    """
    with _client() as client:
        resp = client.get(f"/api/v1/bookmarks/{bookmark_id}")
        resp.raise_for_status()
        b = resp.json()
    return json.dumps({
        "id": b["id"],
        "title": b.get("title", ""),
        "content": b.get("content", {}),
        "summary": b.get("summary", ""),
        "note": b.get("note", ""),
        "tags": [t.get("name", "") for t in b.get("tags", [])],
        "favourited": b.get("favourited", False),
        "archived": b.get("archived", False),
        "created_at": b.get("createdAt", ""),
    }, indent=2)


@mcp.tool()
def create_bookmark(url: str, title: str = "", tags: str = "") -> str:
    """Create a new bookmark from a URL.

    Args:
        url: URL to bookmark
        title: Custom title (optional, auto-fetched if empty)
        tags: Comma-separated tags (optional)
    """
    payload = {
        "type": "link",
        "url": url,
    }
    if title:
        payload["title"] = title

    with _client() as client:
        resp = client.post("/api/v1/bookmarks", json=payload)
        resp.raise_for_status()
        bookmark = resp.json()

    # Add tags if specified
    if tags and bookmark.get("id"):
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            client.post(f"/api/v1/bookmarks/{bookmark['id']}/tags", json={"tagName": tag})

    return json.dumps({
        "status": "created",
        "id": bookmark.get("id"),
        "title": bookmark.get("title", ""),
    }, indent=2)


@mcp.tool()
def list_tags() -> str:
    """List all tags with bookmark counts."""
    with _client() as client:
        resp = client.get("/api/v1/tags")
        resp.raise_for_status()
        data = resp.json()

    tags = data.get("tags", [])
    return json.dumps([{
        "id": t["id"],
        "name": t.get("name", ""),
        "count": t.get("count", 0),
    } for t in tags], indent=2)


@mcp.tool()
def list_lists() -> str:
    """List all bookmark lists."""
    with _client() as client:
        resp = client.get("/api/v1/lists")
        resp.raise_for_status()
        data = resp.json()

    lists = data.get("lists", [])
    return json.dumps([{
        "id": l["id"],
        "name": l.get("name", ""),
        "icon": l.get("icon", ""),
    } for l in lists], indent=2)


@mcp.tool()
def get_list_bookmarks(list_id: str, limit: int = 25) -> str:
    """Get bookmarks in a specific list.

    Args:
        list_id: List ID
        limit: Max results (default: 25)
    """
    with _client() as client:
        resp = client.get(f"/api/v1/lists/{list_id}/bookmarks", params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()

    bookmarks = data.get("bookmarks", [])
    return json.dumps([{
        "id": b["id"],
        "title": b.get("title", ""),
        "url": b.get("content", {}).get("url", "") if b.get("content", {}).get("type") == "link" else "",
        "tags": [t.get("name", "") for t in b.get("tags", [])],
    } for b in bookmarks], indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
