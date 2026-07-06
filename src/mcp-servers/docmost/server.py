"""MCP Server for DocMost (wiki & documentation).

Provides tools to interact with DocMost via its REST API.
Content is automatically converted from markdown to ProseMirror JSON format.

Env vars:
  DOCMOST_URL, DOCMOST_API_KEY, DOCMOST_USER, DOCMOST_PASSWORD
"""

import json
import logging
import os
import re
import uuid

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("docmost")

DOCMOST_URL = os.getenv("DOCMOST_URL", "")
DOCMOST_API_KEY = os.getenv("DOCMOST_API_KEY", "")
DOCMOST_USER = os.getenv("DOCMOST_USER", "")
DOCMOST_PASSWORD = os.getenv("DOCMOST_PASSWORD", "")

_session_cookies: dict = {}


def _pid() -> str:
    return uuid.uuid4().hex[:12]


def _parse_inline(text: str) -> list:
    nodes = []
    parts = re.split(r"(\*\*[^*]+?\*\*|`[^`]+?`)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            nodes.append({"type": "text", "text": part[2:-2],
                          "marks": [{"type": "bold"}]})
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            nodes.append({"type": "text", "text": part[1:-1],
                          "marks": [{"type": "code"}]})
        else:
            nodes.append({"type": "text", "text": part})
    return [n for n in nodes if n.get("text")]


def _md_to_prosemirror(text: str) -> dict:
    """Convert markdown / plain text to a ProseMirror doc JSON object."""
    # Already ProseMirror JSON?
    stripped = text.strip()
    if stripped.startswith("{") and '"type"' in stripped:
        try:
            obj = json.loads(stripped)
            if obj.get("type") == "doc":
                return obj
        except json.JSONDecodeError:
            pass

    nodes: list = []
    in_code = False
    code_lang = ""
    code_lines: list = []
    list_items: list = []
    list_type = "bullet"

    def flush_list():
        if not list_items:
            return
        ttype = "orderedList" if list_type == "ordered" else "bulletList"
        nodes.append({
            "type": ttype,
            "content": [
                {
                    "type": "listItem",
                    "attrs": {"id": _pid()},
                    "content": [{
                        "type": "paragraph",
                        "attrs": {"id": _pid(), "textAlign": None},
                        "content": _parse_inline(item),
                    }],
                }
                for item in list_items
            ],
        })
        list_items.clear()

    for line in text.split("\n"):
        if line.startswith("```"):
            if in_code:
                flush_list()
                nodes.append({
                    "type": "codeBlock",
                    "attrs": {"id": _pid(), "language": code_lang or None},
                    "content": ([{"type": "text", "text": "\n".join(code_lines)}]
                                if code_lines else []),
                })
                code_lines.clear(); code_lang = ""; in_code = False
            else:
                code_lang = line[3:].strip(); in_code = True
            continue
        if in_code:
            code_lines.append(line); continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line.strip()):
            flush_list()
            nodes.append({"type": "horizontalRule", "attrs": {"id": _pid()}}); continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_list()
            level = min(len(m.group(1)), 6)
            content = _parse_inline(m.group(2).strip())
            if content:
                nodes.append({"type": "heading",
                              "attrs": {"id": _pid(), "level": level,
                                        "textAlign": None, "textColor": None},
                              "content": content})
            continue
        m = re.match(r"^\d+\.\s+(.*)", line)
        if m:
            list_type = "ordered"; list_items.append(m.group(1)); continue
        m = re.match(r"^[*\-]\s+(.*)", line)
        if m:
            list_type = "bullet"; list_items.append(m.group(1)); continue
        if not line.strip():
            flush_list(); continue
        flush_list()
        content = _parse_inline(line)
        if content:
            nodes.append({"type": "paragraph",
                          "attrs": {"id": _pid(), "textAlign": None},
                          "content": content})

    flush_list()
    if not nodes:
        nodes.append({"type": "paragraph",
                      "attrs": {"id": _pid(), "textAlign": None}, "content": []})
    return {"type": "doc", "content": nodes}


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
        return httpx.Client(base_url=DOCMOST_URL,
                            headers={"Authorization": f"Bearer {DOCMOST_API_KEY}"},
                            timeout=30)
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
    """List pages in a space (sidebar tree). page_id = parent for children."""
    body = {"spaceId": space_id, "limit": limit, "page": page}
    if page_id:
        body["pageId"] = page_id
    with _client() as c:
        resp = c.post("/api/pages/sidebar-pages", json=body)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", data.get("data", data))
    if isinstance(items, list):
        return json.dumps([{"id": p.get("id"), "title": p.get("title"),
                            "position": p.get("position")} for p in items], indent=2)
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
    """Create a new page. content accepts markdown or ProseMirror JSON string."""
    body: dict = {"spaceId": space_id, "title": title}
    if content:
        body["content"] = _md_to_prosemirror(content)
    if parent_page_id:
        body["parentPageId"] = parent_page_id
    with _client() as c:
        resp = c.post("/api/pages/create", json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def update_page(page_id: str, title: str = "", content: str = "",
                parent_page_id: str = "") -> str:
    """Update an existing page. content accepts markdown or ProseMirror JSON string.
    parent_page_id moves the page under a new parent."""
    body: dict = {"pageId": page_id}
    if title:
        body["title"] = title
    if content:
        body["content"] = _md_to_prosemirror(content)
    if parent_page_id:
        body["parentPageId"] = parent_page_id
    with _client() as c:
        resp = c.post("/api/pages/update", json=body)
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
