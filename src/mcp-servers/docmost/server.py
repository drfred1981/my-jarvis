"""MCP Server for DocMost (wiki & documentation).

Content is converted from markdown to TipTap/ProseMirror JSON using
a built-in converter before being sent to the Docmost API (format=json).

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


# ---------------------------------------------------------------------------
# Markdown → TipTap/ProseMirror JSON converter (same as archiver)
# ---------------------------------------------------------------------------

def _pid() -> str:
    return uuid.uuid4().hex[:12]


_INLINE_RE = re.compile(
    r"(\*\*|__)(?P<bold>.+?)(\*\*|__)"
    r"|(\*|_)(?P<italic>.+?)(\*|_)"
    r"|~~(?P<strike>.+?)~~"
    r"|`(?P<code>[^`]+?)`"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<link_href>[^)]+)\)"
    r"|(?P<text>[^*_~`\[]+)"
)


def _parse_inline(text: str) -> list:
    nodes = []
    for m in _INLINE_RE.finditer(text):
        if m.group("bold"):
            nodes.append({"type": "text", "text": m.group("bold"),
                          "marks": [{"type": "bold"}]})
        elif m.group("italic"):
            nodes.append({"type": "text", "text": m.group("italic"),
                          "marks": [{"type": "italic"}]})
        elif m.group("strike"):
            nodes.append({"type": "text", "text": m.group("strike"),
                          "marks": [{"type": "strike"}]})
        elif m.group("code"):
            nodes.append({"type": "text", "text": m.group("code"),
                          "marks": [{"type": "code"}]})
        elif m.group("link_text"):
            nodes.append({"type": "text", "text": m.group("link_text"),
                          "marks": [{"type": "link", "attrs": {
                              "href": m.group("link_href"), "target": "_blank"}}]})
        elif m.group("text"):
            nodes.append({"type": "text", "text": m.group("text")})
    return [n for n in nodes if n.get("text")]


def _para(text: str) -> dict:
    return {"type": "paragraph", "attrs": {"id": _pid(), "textAlign": None},
            "content": _parse_inline(text) or [{"type": "text", "text": ""}]}


def _heading(level: int, text: str) -> dict:
    return {"type": "heading",
            "attrs": {"id": _pid(), "level": level,
                      "textAlign": None, "textColor": None},
            "content": _parse_inline(text)}


def _li(text: str) -> dict:
    return {"type": "listItem", "attrs": {"id": _pid()}, "content": [_para(text)]}


def md_to_tiptap(text: str) -> dict:
    """Convert a Markdown string to a TipTap/ProseMirror doc dict."""
    nodes: list = []
    in_code = False
    code_lang = ""
    code_lines: list = []
    bullet_items: list = []
    ordered_items: list = []
    quote_lines: list = []

    def flush_bullet():
        if bullet_items:
            nodes.append({"type": "bulletList",
                           "content": [_li(i) for i in bullet_items]})
            bullet_items.clear()

    def flush_ordered():
        if ordered_items:
            nodes.append({"type": "orderedList", "attrs": {"start": 1},
                           "content": [_li(i) for i in ordered_items]})
            ordered_items.clear()

    def flush_quote():
        if quote_lines:
            inner = md_to_tiptap("\n".join(quote_lines))
            nodes.append({"type": "blockquote", "content": inner["content"]})
            quote_lines.clear()

    def flush_all():
        flush_bullet(); flush_ordered(); flush_quote()

    for line in text.split("\n"):
        if line.startswith("```"):
            if in_code:
                flush_all()
                nodes.append({"type": "codeBlock",
                               "attrs": {"id": _pid(), "language": code_lang or None},
                               "content": ([{"type": "text", "text": "\n".join(code_lines)}]
                                            if code_lines else [])})
                code_lines.clear(); code_lang = ""; in_code = False
            else:
                flush_all(); code_lang = line[3:].strip(); in_code = True
            continue
        if in_code:
            code_lines.append(line); continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line.strip()):
            flush_all()
            nodes.append({"type": "horizontalRule", "attrs": {"id": _pid()}}); continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_all()
            lvl = min(len(m.group(1)), 6); txt = m.group(2).strip()
            if txt: nodes.append(_heading(lvl, txt))
            continue
        m = re.match(r"^>\s?(.*)", line)
        if m:
            flush_bullet(); flush_ordered(); quote_lines.append(m.group(1)); continue
        elif quote_lines:
            flush_quote()
        m = re.match(r"^\d+\.\s+(.*)", line)
        if m:
            flush_bullet(); flush_quote(); ordered_items.append(m.group(1)); continue
        elif ordered_items and not line.strip():
            flush_ordered()
        m = re.match(r"^[*\-]\s+(.*)", line)
        if m:
            flush_ordered(); flush_quote(); bullet_items.append(m.group(1)); continue
        elif bullet_items and not line.strip():
            flush_bullet()
        if not line.strip():
            flush_all(); continue
        flush_all(); nodes.append(_para(line))

    flush_all()
    if in_code and code_lines:
        nodes.append({"type": "codeBlock",
                       "attrs": {"id": _pid(), "language": code_lang or None},
                       "content": [{"type": "text", "text": "\n".join(code_lines)}]})
    if not nodes:
        nodes.append(_para(""))
    return {"type": "doc", "content": nodes}


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def _authenticate() -> dict:
    global _session_cookies
    if _session_cookies:
        return _session_cookies
    with httpx.Client(base_url=DOCMOST_URL, timeout=30) as c:
        resp = c.post("/api/auth/login",
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


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

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
    """List pages in a space. page_id = parent for children (empty = root)."""
    body = {"spaceId": space_id, "limit": min(limit, 100), "page": page}
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
    """Create a new page. content is markdown (converted to TipTap JSON).

    Args:
        space_id: Space ID
        title: Page title
        content: Markdown content (optional)
        parent_page_id: Parent page ID (optional, for nesting)
    """
    body: dict = {"spaceId": space_id, "title": title}
    if content:
        body["content"] = md_to_tiptap(content)
        body["format"] = "json"
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
        content: Markdown content (optional, converted to TipTap JSON)
        operation: 'replace' (default), 'append', or 'prepend'
    """
    body: dict = {"pageId": page_id}
    if title:
        body["title"] = title
    if content:
        body["content"] = md_to_tiptap(content)
        body["format"] = "json"
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
        resp = c.post("/api/comments/",
                      json={"pageId": page_id, "limit": limit, "page": page})
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
        resp = c.post("/api/comments/create",
                      json={"pageId": page_id, "content": content})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
