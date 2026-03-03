"""MCP Server for MIND (self-hosted reminder/notification system).

Provides tools to interact with MIND via its REST API:
- List, create, search and manage reminders
- List and trigger static reminders (one-click notifications)
- List notification services and templates

Requires env vars:
  MIND_URL=http://mind.default.svc.cluster.local:8080
  MIND_USER=admin
  MIND_PASSWORD=secret
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("mind")

MIND_URL = os.getenv("MIND_URL", "").rstrip("/")
MIND_USER = os.getenv("MIND_USER", "")
MIND_PASSWORD = os.getenv("MIND_PASSWORD", "")

_api_key: str = ""


def _authenticate() -> str:
    """Authenticate and return API key."""
    global _api_key
    if _api_key:
        return _api_key
    with httpx.Client(base_url=MIND_URL, timeout=30) as client:
        resp = client.post(
            "/api/auth/login",
            json={"username": MIND_USER, "password": MIND_PASSWORD},
        )
        resp.raise_for_status()
        data = resp.json()
        _api_key = data.get("result", {}).get("api_key", "")
        if not _api_key:
            raise ValueError("No api_key in login response")
        return _api_key


def _client() -> httpx.Client:
    key = _authenticate()
    return httpx.Client(
        base_url=MIND_URL,
        params={"api_key": key},
        timeout=30,
    )


def _request(method: str, path: str, **kwargs) -> dict:
    """Make a request, re-authenticating on 401."""
    global _api_key
    with _client() as client:
        resp = getattr(client, method)(f"/api{path}", **kwargs)
        if resp.status_code == 401:
            _api_key = ""
            with _client() as client2:
                resp = getattr(client2, method)(f"/api{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


# --- Reminders ---


@mcp.tool()
def list_reminders() -> str:
    """Get a list of all reminders with their schedule and status."""
    data = _request("get", "/reminders")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_reminder(reminder_id: int) -> str:
    """Get details of a specific reminder.

    Args:
        reminder_id: Reminder ID
    """
    data = _request("get", f"/reminders/{reminder_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def create_reminder(
    title: str,
    notification_service_id: int,
    text: str = "",
    time: str = "",
    repeat_quantity: int = 0,
    repeat_interval: str = "",
) -> str:
    """Create a new reminder.

    Args:
        title: Reminder title
        notification_service_id: ID of the notification service to use
        text: Notification text/body (optional)
        time: When to send, ISO format e.g. "2026-03-15T09:00:00" (optional)
        repeat_quantity: How many times to repeat (0 = no repeat)
        repeat_interval: Repeat interval: "minutes", "hours", "days", "weeks", "months", "years"
    """
    payload = {
        "title": title,
        "notification_service_id": notification_service_id,
    }
    if text:
        payload["text"] = text
    if time:
        payload["time"] = time
    if repeat_quantity and repeat_interval:
        payload["repeat_quantity"] = repeat_quantity
        payload["repeat_interval"] = repeat_interval

    data = _request("post", "/reminders", json=payload)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def delete_reminder(reminder_id: int) -> str:
    """Delete a reminder.

    Args:
        reminder_id: Reminder ID
    """
    data = _request("delete", f"/reminders/{reminder_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def search_reminders(query: str) -> str:
    """Search reminders by keyword.

    Args:
        query: Search query
    """
    data = _request("get", "/reminders/search", params={"query": query})
    return json.dumps(data, indent=2, default=str)


# --- Static Reminders ---


@mcp.tool()
def list_static_reminders() -> str:
    """List all static reminders (one-click send notifications)."""
    data = _request("get", "/staticreminders")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def trigger_static_reminder(static_reminder_id: int) -> str:
    """Trigger a static reminder to send its notification immediately.

    Args:
        static_reminder_id: Static reminder ID
    """
    data = _request("post", f"/staticreminders/{static_reminder_id}")
    return json.dumps(data, indent=2, default=str)


# --- Notification Services ---


@mcp.tool()
def list_notification_services() -> str:
    """Get a list of all configured notification services."""
    data = _request("get", "/notificationservices")
    return json.dumps(data, indent=2, default=str)


# --- Templates ---


@mcp.tool()
def list_templates() -> str:
    """Get a list of all reminder templates."""
    data = _request("get", "/templates")
    return json.dumps(data, indent=2, default=str)


# --- System ---


@mcp.tool()
def get_about() -> str:
    """Get MIND application info and version."""
    data = _request("get", "/about")
    return json.dumps(data, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
