"""MCP Server for DocMost (wiki & documentation).

Uses format=markdown for all content operations — Docmost converts to ProseMirror.

Env vars:
  DOCMOST_URL, DOCMOST_API_KEY, DOCMOST_USER, DOCMOST_PASSWORD
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("docmost")

DOCMOST_URL = os.getenv("DOCMOST_URL", "")
DOCMOST_API_KEY = os.getenv("DOCMOST_API_KEY", "")
DOCMOST_USER = os.getenv("DOCMOST_USER", "")
DOCMOST_PASSWORD = os.getenv("DOCMOST_PASSWORD", "")

_session_cookies: dict = {}


def _authenticate() -> dict:
    global _session_cookies
    if _session_cookies:
        return _session_cookies
    with httpx.Client(base_url=DOCMOST_URL, timeout=30) as client:
        resp = client.post("/api/auth/login",
                           json={"email": DOCMOST_USER, "password": DOCMOST_PASSWORD})
        resp.raise_for_status()
        _session_cookies = dict(resp.cookies)
    return _session_cookies


def _client() -> httpx.Client:
    if DOCMOST_API_KEY:
        return httpx.Client(
            base_url=DOCMOST_URL,
            headers={"Authorization": f"Bearer {DOCMOST_API_KEY}"},
            timeout=30,
        )
    return httpx.Client(base_url=DOCMOST_URL, cookies=_authenticate(), timeout=30)


@mcp.tool()
def list_spaces(limit: int = 20, page: int = 1) -> str:
    """List all spaces in the workspace."""
    with _client() as c:
        resp = c.post("/api/spaces/", json={"limit": limit, "page": page})
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{"id": s.get("id"), "name": s.get("name"),
                            "slug": s.get("slug")} for s in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def get_space(space_id: str) -> str:
    """Get details of a specific space."""
    with _client() as c:
        resp = c.post("/api/spaces/info", json={"spaceId": space_id})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def list_pages(space_id: str, page_id: str = "", limit: int = 50, page: int = 1) -> str:
    """List pages in a space. page_id = parent page for children (empty = root)."""
    body = {"spaceId": space_id, "limit": limit, "page": page}
    if page_id:
        body["pageId"] = page_id
    with _client() as c:
        resp = c.post("/api/pages/sidebar-pages", json=body)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, dict):
        items = items.get("items", [])
    if isinstance(items, list):
        return json.dumps([{"id": p.get("id"), "title": p.get("title"),
                            "position": p.get("position"),
                            "parentPageId": p.get("parentPageId"),
                            "hasChildren": p.get("hasChildren")} for p in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def get_page(page_id: str) -> str:
    """Get full content of a page."""
    with _client() as c:
        resp = c.post("/api/pages/info", json={"pageId": page_id})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def create_page(space_id: str, title: str, content: str = "",
                parent_page_id: str = "") -> str:
    """Create a new page. content is markdown text (converted server-side to ProseMirror)."""
    body: dict = {"spaceId": space_id, "title": title}
    if content:
        body["content"] = content
        body["format"] = "markdown"
    if parent_page_id:
        body["parentPageId"] = parent_page_id
    with _client() as c:
        resp = c.post("/api/pages/create", json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def update_page(page_id: str, title: str = "", content: str = "",
                operation: str = "replace") -> str:
    """Update an existing page.

    Args:
        page_id: Page ID to update
        title: New title (optional)
        content: Markdown content (optional). operation controls how it's applied.
        operation: 'replace' (default), 'append', or 'prepend'
    """
    body: dict = {"pageId": page_id}
    if title:
        body["title"] = title
    if content:
        body["content"] = content
        body["format"] = "markdown"
        body["operation"] = operation
    with _client() as c:
        resp = c.post("/api/pages/update", json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def move_page(page_id: str, parent_page_id: str, position: str = "a05WZ") -> str:
    """Move a page under a new parent.

    Args:
        page_id: Page ID to move
        parent_page_id: New parent page ID
        position: Lexorank position string (5-12 chars, default 'a05WZ')
    """
    with _client() as c:
        resp = c.post("/api/pages/move",
                      json={"pageId": page_id, "parentPageId": parent_page_id,
                            "position": position})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def delete_page(page_id: str) -> str:
    """Delete a page."""
    with _client() as c:
        resp = c.post("/api/pages/delete", json={"pageId": page_id})
        resp.raise_for_status()
    return json.dumps({"status": "deleted", "pageId": page_id})


@mcp.tool()
def search_pages(query: str, space_id: str = "", limit: int = 20) -> str:
    """Search pages by text content."""
    body = {"query": query, "limit": limit}
    if space_id:
        body["spaceId"] = space_id
    with _client() as c:
        resp = c.post("/api/search", json=body)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{"id": p.get("id"), "title": p.get("title"),
                            "highlight": p.get("highlight", "")} for p in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def get_recent_pages(space_id: str = "", limit: int = 20, page: int = 1) -> str:
    """Get recently modified pages."""
    body = {"limit": limit, "page": page}
    if space_id:
        body["spaceId"] = space_id
    with _client() as c:
        resp = c.post("/api/pages/recent", json=body)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{"id": p.get("id"), "title": p.get("title"),
                            "updatedAt": p.get("updatedAt", "")} for p in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def list_comments(page_id: str, limit: int = 50, page: int = 1) -> str:
    """List comments on a page."""
    with _client() as c:
        resp = c.post("/api/comments/", json={"pageId": page_id, "limit": limit, "page": page})
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{"id": c.get("id"), "content": c.get("content", ""),
                            "createdAt": c.get("createdAt", "")} for c in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def create_comment(page_id: str, content: str) -> str:
    """Add a comment to a page."""
    with _client() as c:
        resp = c.post("/api/comments/create", json={"pageId": page_id, "content": content})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
