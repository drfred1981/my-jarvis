"""MCP Server for Planka (project management / Kanban).

Provides tools to manage boards, lists, cards, and comments via Planka REST API.
API docs: https://docs.planka.cloud/docs/api/
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("planka")

PLANKA_URL = os.getenv("PLANKA_URL", "http://planka.default.svc.cluster.local:1337")
PLANKA_USER = os.getenv("PLANKA_USER", "")
PLANKA_PASSWORD = os.getenv("PLANKA_PASSWORD", "")

_token: str | None = None


def _authenticate() -> str:
    """Authenticate and return access token."""
    global _token
    if _token:
        return _token
    with httpx.Client(base_url=PLANKA_URL, timeout=30) as client:
        resp = client.post("/api/access-tokens", json={
            "emailOrUsername": PLANKA_USER,
            "password": PLANKA_PASSWORD,
        })
        resp.raise_for_status()
        _token = resp.json().get("item", "")
        return _token


def _client() -> httpx.Client:
    token = _authenticate()
    return httpx.Client(
        base_url=PLANKA_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )


@mcp.tool()
def list_projects() -> str:
    """List all Planka projects."""
    with _client() as client:
        resp = client.get("/api/projects")
        resp.raise_for_status()
        data = resp.json()
    projects = data.get("items", [])
    return json.dumps([{
        "id": p["id"],
        "name": p["name"],
    } for p in projects], indent=2)


@mcp.tool()
def get_project(project_id: str) -> str:
    """Get a project with its boards.

    Args:
        project_id: Planka project ID
    """
    with _client() as client:
        resp = client.get(f"/api/projects/{project_id}")
        resp.raise_for_status()
        data = resp.json()
    project = data.get("item", {})
    boards = data.get("included", {}).get("boards", [])
    return json.dumps({
        "id": project.get("id"),
        "name": project.get("name"),
        "boards": [{"id": b["id"], "name": b["name"], "position": b.get("position")} for b in boards],
    }, indent=2)


@mcp.tool()
def get_board(board_id: str) -> str:
    """Get a board with its lists and cards.

    Args:
        board_id: Planka board ID
    """
    with _client() as client:
        resp = client.get(f"/api/boards/{board_id}")
        resp.raise_for_status()
        data = resp.json()
    included = data.get("included", {})
    lists = included.get("lists", [])
    cards = included.get("cards", [])

    lists_with_cards = []
    for lst in sorted(lists, key=lambda x: x.get("position", 0)):
        list_cards = [c for c in cards if c.get("listId") == lst["id"]]
        list_cards.sort(key=lambda x: x.get("position", 0))
        lists_with_cards.append({
            "id": lst["id"],
            "name": lst["name"],
            "cards": [{
                "id": c["id"],
                "name": c["name"],
                "description": c.get("description", ""),
                "dueDate": c.get("dueDate"),
                "isCompleted": c.get("isCompleted", False),
            } for c in list_cards],
        })
    return json.dumps(lists_with_cards, indent=2)


@mcp.tool()
def get_card(card_id: str) -> str:
    """Get card details including comments and labels.

    Args:
        card_id: Planka card ID
    """
    with _client() as client:
        resp = client.get(f"/api/cards/{card_id}")
        resp.raise_for_status()
        data = resp.json()
    card = data.get("item", {})
    included = data.get("included", {})
    return json.dumps({
        "id": card.get("id"),
        "name": card.get("name"),
        "description": card.get("description"),
        "dueDate": card.get("dueDate"),
        "isCompleted": card.get("isCompleted"),
        "labels": [{"id": l["id"], "name": l.get("name"), "color": l.get("color")}
                    for l in included.get("cardLabels", [])],
        "tasks": [{"id": t["id"], "name": t["name"], "isCompleted": t.get("isCompleted")}
                  for t in included.get("tasks", [])],
        "comments": [{"id": c["id"], "text": c.get("text"), "createdAt": c.get("createdAt")}
                     for c in included.get("actions", []) if c.get("type") == "commentCard"],
    }, indent=2)


@mcp.tool()
def create_card(board_id: str, list_id: str, name: str, description: str = "", due_date: str = "") -> str:
    """Create a new card in a list.

    Args:
        board_id: Board ID
        list_id: List ID where the card will be created
        name: Card title
        description: Card description (optional)
        due_date: Due date in ISO format (optional)
    """
    payload = {"name": name, "position": 65535}
    if description:
        payload["description"] = description
    if due_date:
        payload["dueDate"] = due_date

    with _client() as client:
        resp = client.post(f"/api/lists/{list_id}/cards", json=payload)
        resp.raise_for_status()
        card = resp.json().get("item", {})
    return json.dumps({"status": "created", "id": card.get("id"), "name": card.get("name")}, indent=2)


@mcp.tool()
def move_card(card_id: str, list_id: str, position: int = 65535) -> str:
    """Move a card to a different list.

    Args:
        card_id: Card ID to move
        list_id: Target list ID
        position: Position in the list (default: end)
    """
    with _client() as client:
        resp = client.patch(f"/api/cards/{card_id}", json={
            "listId": list_id,
            "position": position,
        })
        resp.raise_for_status()
    return json.dumps({"status": "moved", "card_id": card_id, "to_list": list_id})


@mcp.tool()
def add_comment(card_id: str, text: str) -> str:
    """Add a comment to a card.

    Args:
        card_id: Card ID
        text: Comment text
    """
    with _client() as client:
        resp = client.post(f"/api/cards/{card_id}/comment-actions", json={"text": text})
        resp.raise_for_status()
        comment = resp.json().get("item", {})
    return json.dumps({"status": "commented", "id": comment.get("id")})


if __name__ == "__main__":
    mcp.run(transport="stdio")
