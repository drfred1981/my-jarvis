"""MCP Server for Trilium Notes (ETAPI).

Provides tools to interact with Trilium Notes via its External Takeover API:
- Create, read, update, delete notes
- Search notes by query or ancestor
- Manage branches (parent-child links)
- Append or replace note content

Requires env vars:
  TRILIUM_URL=http://trilium.trilium.svc.cluster.local:8080
  TRILIUM_ETAPI_TOKEN=<token from Trilium Options → ETAPI>
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("trilium")

TRILIUM_URL = os.getenv("TRILIUM_URL", "").rstrip("/")
TRILIUM_ETAPI_TOKEN = os.getenv("TRILIUM_ETAPI_TOKEN", "")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=TRILIUM_URL + "/etapi",
        headers={"Authorization": f"Bearer {TRILIUM_ETAPI_TOKEN}"},
        timeout=30,
    )


@mcp.tool()
def get_app_info() -> str:
    """Get Trilium server info (version, db version, UTC time offset)."""
    with _client() as c:
        r = c.get("/app-info")
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


@mcp.tool()
def get_note(note_id: str) -> str:
    """Get note metadata (title, type, mime, attributes).

    Args:
        note_id: Trilium note ID (e.g. 'root', 'abc123def456')
    """
    with _client() as c:
        r = c.get(f"/notes/{note_id}")
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


@mcp.tool()
def get_note_content(note_id: str) -> str:
    """Get the raw content of a note (HTML for text notes, plain text for code notes).

    Args:
        note_id: Trilium note ID
    """
    with _client() as c:
        r = c.get(f"/notes/{note_id}/content")
        r.raise_for_status()
    return r.text


@mcp.tool()
def create_note(
    parent_note_id: str,
    title: str,
    content: str = "",
    note_type: str = "text",
    content_type: str = "text/html",
) -> str:
    """Create a new note under a parent.

    Args:
        parent_note_id: Parent note ID ('root' for top level)
        title: Note title
        content: Note content (HTML for text notes, raw text for code notes)
        note_type: 'text' (default), 'code', 'file', 'book'
        content_type: 'text/html' (default), 'text/plain', 'text/x-markdown'
    """
    with _client() as c:
        r = c.post("/create-note", json={
            "parentNoteId": parent_note_id,
            "title": title,
            "type": note_type,
            "content": content,
            "mime": content_type,
        })
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


@mcp.tool()
def update_note_title(note_id: str, title: str) -> str:
    """Update a note's title.

    Args:
        note_id: Trilium note ID
        title: New title
    """
    with _client() as c:
        r = c.patch(f"/notes/{note_id}", json={"title": title})
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


@mcp.tool()
def update_note_content(note_id: str, content: str, content_type: str = "text/html") -> str:
    """Replace a note's content entirely.

    Args:
        note_id: Trilium note ID
        content: New content (HTML string for text notes)
        content_type: 'text/html' (default) or 'text/plain'
    """
    with _client() as c:
        r = c.put(
            f"/notes/{note_id}/content",
            content=content.encode("utf-8"),
            headers={"Content-Type": content_type},
        )
        r.raise_for_status()
    return json.dumps({"ok": True, "note_id": note_id})


@mcp.tool()
def append_to_note(note_id: str, content: str, content_type: str = "text/html") -> str:
    """Append content to an existing note (fetches current, concatenates, writes back).

    Args:
        note_id: Trilium note ID
        content: HTML (or plain text) to append
        content_type: 'text/html' (default) or 'text/plain'
    """
    with _client() as c:
        r_get = c.get(f"/notes/{note_id}/content")
        current = r_get.text if r_get.status_code == 200 else ""
        updated = current + content
        r_put = c.put(
            f"/notes/{note_id}/content",
            content=updated.encode("utf-8"),
            headers={"Content-Type": content_type},
        )
        r_put.raise_for_status()
    return json.dumps({"ok": True, "note_id": note_id, "total_bytes": len(updated)})


@mcp.tool()
def delete_note(note_id: str) -> str:
    """Delete a note and all its children.

    Args:
        note_id: Trilium note ID
    """
    with _client() as c:
        r = c.delete(f"/notes/{note_id}")
        r.raise_for_status()
    return json.dumps({"ok": True, "deleted": note_id})


@mcp.tool()
def search_notes(
    query: str,
    ancestor_note_id: str = "",
    limit: int = 20,
    fast_search: bool = False,
) -> str:
    """Search notes using Trilium search syntax.

    Trilium search examples:
      - 'note.title = \"My Title\"'   — exact title
      - 'meeting notes'               — full text search
      - '#tag = value'                — by label attribute

    Args:
        query: Search string (Trilium search syntax or plain text)
        ancestor_note_id: Limit search to descendants of this note (optional)
        limit: Max results (default 20)
        fast_search: Use fast (title-only) search (default False = full text)
    """
    params: dict = {
        "search": query,
        "fastSearch": str(fast_search).lower(),
        "limit": str(limit),
        "includeArchivedNotes": "false",
    }
    if ancestor_note_id:
        params["ancestorNoteId"] = ancestor_note_id

    with _client() as c:
        r = c.get("/notes", params=params)
        r.raise_for_status()
        data = r.json()

    if isinstance(data, dict) and "results" in data:
        results = data["results"]
    elif isinstance(data, list):
        results = data
    else:
        results = []

    return json.dumps({
        "count": len(results),
        "notes": [
            {"noteId": n["noteId"], "title": n["title"], "type": n.get("type", "")}
            for n in results
        ],
    }, indent=2)


@mcp.tool()
def get_note_branches(note_id: str) -> str:
    """List all branches (parent-child relationships) of a note.

    Returns both parent branches and child branches.

    Args:
        note_id: Trilium note ID
    """
    with _client() as c:
        r = c.get(f"/notes/{note_id}/branches")
        r.raise_for_status()
        data = r.json()

    return json.dumps(data, indent=2)


@mcp.tool()
def create_branch(
    note_id: str,
    parent_note_id: str,
    prefix: str = "",
    note_position: int = 10,
) -> str:
    """Link an existing note to an additional parent (create a branch/clone).

    Args:
        note_id: Note to link
        parent_note_id: New parent to link under
        prefix: Optional text prefix shown in tree (default empty)
        note_position: Position in parent's children list (default 10)
    """
    with _client() as c:
        r = c.post("/branches", json={
            "noteId": note_id,
            "parentNoteId": parent_note_id,
            "notePosition": note_position,
            "prefix": prefix,
            "isExpanded": False,
        })
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


@mcp.tool()
def delete_branch(branch_id: str) -> str:
    """Remove a branch (unlinks note from parent; note is not deleted unless it has no other parents).

    Args:
        branch_id: Branch ID (from get_note_branches)
    """
    with _client() as c:
        r = c.delete(f"/branches/{branch_id}")
        r.raise_for_status()
    return json.dumps({"ok": True, "deleted_branch": branch_id})


@mcp.tool()
def get_note_attributes(note_id: str) -> str:
    """List all attributes (labels and relations) of a note.

    Args:
        note_id: Trilium note ID
    """
    with _client() as c:
        r = c.get(f"/notes/{note_id}/attributes")
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


@mcp.tool()
def create_attribute(
    note_id: str,
    attr_type: str,
    name: str,
    value: str = "",
    is_inheritable: bool = False,
) -> str:
    """Add a label or relation attribute to a note.

    Args:
        note_id: Note to attach attribute to
        attr_type: 'label' or 'relation'
        name: Attribute name (e.g. 'archived', 'source', 'priority')
        value: Attribute value (empty string for boolean labels)
        is_inheritable: Whether child notes inherit this attribute
    """
    with _client() as c:
        r = c.post("/attributes", json={
            "noteId": note_id,
            "type": attr_type,
            "name": name,
            "value": value,
            "isInheritable": is_inheritable,
        })
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
