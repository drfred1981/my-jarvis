"""MCP Server for DocMost (wiki & documentation).

Provides tools to interact with DocMost via its REST API:
- List and manage spaces
- Read, create, update, delete pages
- Search content
- Manage comments

Note: DocMost API uses POST for all endpoints.
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("docmost")

DOCMOST_URL = os.getenv("DOCMOST_URL", "http://docmost.services-it.svc.cluster.local:3000")
DOCMOST_API_KEY = os.getenv("DOCMOST_API_KEY", "")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=DOCMOST_URL,
        headers={"Authorization": f"Bearer {DOCMOST_API_KEY}"},
        timeout=30,
    )


@mcp.tool()
def list_spaces(limit: int = 20, page: int = 1) -> str:
    """List all spaces in the workspace.

    Args:
        limit: Max number of spaces (default: 20)
        page: Page number (default: 1)
    """
    with _client() as client:
        resp = client.post("/api/spaces/", json={"limit": limit, "page": page})
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{
            "id": s.get("id"),
            "name": s.get("name"),
            "slug": s.get("slug"),
            "description": s.get("description", ""),
        } for s in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def get_space(space_id: str) -> str:
    """Get details of a specific space.

    Args:
        space_id: Space ID
    """
    with _client() as client:
        resp = client.post("/api/spaces/info", json={"spaceId": space_id})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def list_pages(space_id: str, page_id: str = "", limit: int = 50, page: int = 1) -> str:
    """List pages in a space (sidebar tree).

    Args:
        space_id: Space ID
        page_id: Parent page ID to list children (empty for root pages)
        limit: Max results (default: 50)
        page: Page number (default: 1)
    """
    body = {"spaceId": space_id, "limit": limit, "page": page}
    if page_id:
        body["pageId"] = page_id
    with _client() as client:
        resp = client.post("/api/pages/sidebar-pages", json=body)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{
            "id": p.get("id"),
            "title": p.get("title"),
            "slug": p.get("slug", ""),
            "icon": p.get("icon", ""),
            "position": p.get("position"),
        } for p in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def get_page(page_id: str) -> str:
    """Get full content of a page.

    Args:
        page_id: Page ID
    """
    with _client() as client:
        resp = client.post("/api/pages/info", json={"pageId": page_id})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def create_page(space_id: str, title: str, content: str = "", parent_page_id: str = "") -> str:
    """Create a new page in a space.

    Args:
        space_id: Space ID where the page will be created
        title: Page title
        content: Page content in markdown/JSON format (optional)
        parent_page_id: Parent page ID for nested pages (optional)
    """
    body = {"spaceId": space_id, "title": title}
    if content:
        body["content"] = content
    if parent_page_id:
        body["parentPageId"] = parent_page_id
    with _client() as client:
        resp = client.post("/api/pages/create", json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def update_page(page_id: str, title: str = "", content: str = "") -> str:
    """Update an existing page.

    Args:
        page_id: Page ID to update
        title: New title (optional, leave empty to keep current)
        content: New content (optional, leave empty to keep current)
    """
    body = {"pageId": page_id}
    if title:
        body["title"] = title
    if content:
        body["content"] = content
    with _client() as client:
        resp = client.post("/api/pages/update", json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def delete_page(page_id: str) -> str:
    """Delete a page.

    Args:
        page_id: Page ID to delete
    """
    with _client() as client:
        resp = client.post("/api/pages/delete", json={"pageId": page_id})
        resp.raise_for_status()
    return json.dumps({"status": "deleted", "pageId": page_id})


@mcp.tool()
def search_pages(query: str, space_id: str = "", limit: int = 20) -> str:
    """Search pages by text content.

    Args:
        query: Search query
        space_id: Filter by space ID (optional)
        limit: Max results (default: 20)
    """
    body = {"query": query, "limit": limit}
    if space_id:
        body["spaceId"] = space_id
    with _client() as client:
        resp = client.post("/api/search", json=body)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{
            "id": p.get("id"),
            "title": p.get("title"),
            "slug": p.get("slug", ""),
            "spaceId": p.get("spaceId", ""),
            "highlight": p.get("highlight", ""),
        } for p in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def get_recent_pages(space_id: str = "", limit: int = 20, page: int = 1) -> str:
    """Get recently modified pages.

    Args:
        space_id: Filter by space ID (optional)
        limit: Max results (default: 20)
        page: Page number (default: 1)
    """
    body = {"limit": limit, "page": page}
    if space_id:
        body["spaceId"] = space_id
    with _client() as client:
        resp = client.post("/api/pages/recent", json=body)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{
            "id": p.get("id"),
            "title": p.get("title"),
            "spaceId": p.get("spaceId", ""),
            "updatedAt": p.get("updatedAt", ""),
            "creatorName": p.get("creator", {}).get("name", "") if isinstance(p.get("creator"), dict) else "",
        } for p in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def list_comments(page_id: str, limit: int = 50, page: int = 1) -> str:
    """List comments on a page.

    Args:
        page_id: Page ID
        limit: Max results (default: 50)
        page: Page number (default: 1)
    """
    with _client() as client:
        resp = client.post("/api/comments/", json={"pageId": page_id, "limit": limit, "page": page})
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{
            "id": c.get("id"),
            "content": c.get("content", ""),
            "creatorId": c.get("creatorId", ""),
            "resolved": c.get("resolved", False),
            "createdAt": c.get("createdAt", ""),
        } for c in items], indent=2)
    return json.dumps(data, indent=2)


@mcp.tool()
def create_comment(page_id: str, content: str) -> str:
    """Add a comment to a page.

    Args:
        page_id: Page ID
        content: Comment content
    """
    with _client() as client:
        resp = client.post("/api/comments/create", json={"pageId": page_id, "content": content})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
