"""MCP Server for Home Assistant.

Provides tools to interact with Home Assistant via its REST API:
- List and inspect entities
- Get entity states
- Call services (turn on/off, scenes, automations)
- Get history and logbook
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("homeassistant")

HA_URL = os.getenv("HA_URL", "http://homeassistant.default.svc.cluster.local:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=HA_URL, headers=_headers(), timeout=30)


@mcp.tool()
def list_entities(domain: str = "") -> str:
    """List all Home Assistant entities, optionally filtered by domain.

    Args:
        domain: Filter by domain (e.g. "light", "switch", "sensor", "automation")
    """
    with _client() as client:
        resp = client.get("/api/states")
        resp.raise_for_status()
        states = resp.json()

    if domain:
        states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]

    result = []
    for s in states:
        result.append({
            "entity_id": s["entity_id"],
            "state": s["state"],
            "friendly_name": s.get("attributes", {}).get("friendly_name", ""),
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_entity_state(entity_id: str) -> str:
    """Get the full state and attributes of an entity.

    Args:
        entity_id: Entity ID (e.g. "light.living_room", "sensor.temperature")
    """
    with _client() as client:
        resp = client.get(f"/api/states/{entity_id}")
        resp.raise_for_status()
        state = resp.json()

    return json.dumps({
        "entity_id": state["entity_id"],
        "state": state["state"],
        "attributes": state.get("attributes", {}),
        "last_changed": state.get("last_changed"),
        "last_updated": state.get("last_updated"),
    }, indent=2)


@mcp.tool()
def call_service(domain: str, service: str, entity_id: str = "", data: str = "{}") -> str:
    """Call a Home Assistant service.

    Args:
        domain: Service domain (e.g. "light", "switch", "scene", "automation")
        service: Service name (e.g. "turn_on", "turn_off", "toggle", "activate")
        entity_id: Target entity ID (optional for some services)
        data: Additional service data as JSON string (optional)
    """
    payload = json.loads(data) if data else {}
    if entity_id:
        payload["entity_id"] = entity_id

    with _client() as client:
        resp = client.post(f"/api/services/{domain}/{service}", json=payload)
        resp.raise_for_status()
        result = resp.json()

    return json.dumps({
        "status": "ok",
        "service": f"{domain}.{service}",
        "affected_entities": len(result) if isinstance(result, list) else 0,
    }, indent=2)


@mcp.tool()
def list_automations() -> str:
    """List all automations with their current state."""
    with _client() as client:
        resp = client.get("/api/states")
        resp.raise_for_status()
        states = resp.json()

    automations = [s for s in states if s["entity_id"].startswith("automation.")]
    result = []
    for a in automations:
        attrs = a.get("attributes", {})
        result.append({
            "entity_id": a["entity_id"],
            "state": a["state"],
            "friendly_name": attrs.get("friendly_name", ""),
            "last_triggered": attrs.get("last_triggered"),
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_history(entity_id: str, hours: int = 24) -> str:
    """Get the state history of an entity.

    Args:
        entity_id: Entity ID to get history for
        hours: Number of hours to look back (default: 24)
    """
    from datetime import datetime, timedelta, timezone

    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with _client() as client:
        resp = client.get(
            f"/api/history/period/{start}",
            params={"filter_entity_id": entity_id, "minimal_response": "true"},
        )
        resp.raise_for_status()
        history = resp.json()

    if not history or not history[0]:
        return json.dumps({"entity_id": entity_id, "history": []})

    entries = []
    for entry in history[0]:
        entries.append({
            "state": entry.get("state"),
            "last_changed": entry.get("last_changed"),
        })
    return json.dumps({"entity_id": entity_id, "entries": len(entries), "history": entries}, indent=2)


@mcp.tool()
def fire_event(event_type: str, event_data: str = "{}") -> str:
    """Fire a Home Assistant event.

    Args:
        event_type: Type of event to fire
        event_data: Event data as JSON string
    """
    payload = json.loads(event_data) if event_data else {}
    with _client() as client:
        resp = client.post(f"/api/events/{event_type}", json=payload)
        resp.raise_for_status()
        return json.dumps({"status": "ok", "event_type": event_type})


@mcp.tool()
def get_config() -> str:
    """Get Home Assistant configuration overview."""
    with _client() as client:
        resp = client.get("/api/config")
        resp.raise_for_status()
        cfg = resp.json()

    return json.dumps({
        "location_name": cfg.get("location_name"),
        "latitude": cfg.get("latitude"),
        "longitude": cfg.get("longitude"),
        "unit_system": cfg.get("unit_system"),
        "time_zone": cfg.get("time_zone"),
        "version": cfg.get("version"),
        "components": len(cfg.get("components", [])),
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
