"""MCP Server for Home Assistant.

Provides tools to interact with Home Assistant via its REST API:
- List, search, and inspect entities
- Get entity states and history with statistics
- Call services (turn on/off, scenes, automations)
- Browse areas, devices, scenes, scripts
- Render Jinja2 templates for complex queries
- Access logbook, error log, calendar events
- System health and diagnostics
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


def _render_template(template: str) -> str:
    """Evaluate a Jinja2 template on Home Assistant."""
    with _client() as client:
        resp = client.post("/api/template", json={"template": template})
        resp.raise_for_status()
        return resp.text


@mcp.tool()
def list_entities(domain: str = "", search: str = "") -> str:
    """List all Home Assistant entities, optionally filtered by domain and/or search text.

    Args:
        domain: Filter by domain (e.g. "light", "switch", "sensor", "automation")
        search: Filter by text in entity_id or friendly_name (case-insensitive)
    """
    with _client() as client:
        resp = client.get("/api/states")
        resp.raise_for_status()
        states = resp.json()

    if domain:
        states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]

    if search:
        q = search.lower()
        states = [
            s for s in states
            if q in s["entity_id"].lower()
            or q in s.get("attributes", {}).get("friendly_name", "").lower()
        ]

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
    """Get the state history of an entity with optional statistics for numeric sensors.

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
    numeric_values = []
    for entry in history[0]:
        state_val = entry.get("state")
        entries.append({
            "state": state_val,
            "last_changed": entry.get("last_changed"),
        })
        try:
            numeric_values.append(float(state_val))
        except (ValueError, TypeError):
            pass

    result = {"entity_id": entity_id, "entries": len(entries), "history": entries}

    if numeric_values:
        result["statistics"] = {
            "min": round(min(numeric_values), 2),
            "max": round(max(numeric_values), 2),
            "avg": round(sum(numeric_values) / len(numeric_values), 2),
            "changes": len(numeric_values),
        }

    return json.dumps(result, indent=2)


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
    """Get Home Assistant configuration overview including loaded integrations."""
    with _client() as client:
        resp = client.get("/api/config")
        resp.raise_for_status()
        cfg = resp.json()

    components = cfg.get("components", [])
    # Extract integration names (remove sub-components like "homeassistant.scene")
    integrations = sorted({c.split(".")[0] for c in components})

    return json.dumps({
        "location_name": cfg.get("location_name"),
        "latitude": cfg.get("latitude"),
        "longitude": cfg.get("longitude"),
        "unit_system": cfg.get("unit_system"),
        "time_zone": cfg.get("time_zone"),
        "version": cfg.get("version"),
        "components_count": len(components),
        "integrations": integrations,
    }, indent=2)


# --- Discovery & Search ---


@mcp.tool()
def search_entities(query: str, domain: str = "") -> str:
    """Search entities by text in entity_id or friendly_name (case-insensitive).

    Args:
        query: Search text (e.g. "temperature", "salon", "battery")
        domain: Optional domain filter (e.g. "sensor", "light")
    """
    with _client() as client:
        resp = client.get("/api/states")
        resp.raise_for_status()
        states = resp.json()

    if domain:
        states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]

    q = query.lower()
    matches = [
        s for s in states
        if q in s["entity_id"].lower()
        or q in s.get("attributes", {}).get("friendly_name", "").lower()
    ]

    result = []
    for s in matches:
        result.append({
            "entity_id": s["entity_id"],
            "state": s["state"],
            "friendly_name": s.get("attributes", {}).get("friendly_name", ""),
        })
    return json.dumps({"query": query, "count": len(result), "results": result}, indent=2)


@mcp.tool()
def list_services(domain: str = "") -> str:
    """List available Home Assistant services, optionally filtered by domain.

    Args:
        domain: Filter by domain (e.g. "light", "climate", "automation")
    """
    with _client() as client:
        resp = client.get("/api/services")
        resp.raise_for_status()
        services = resp.json()

    if domain:
        services = [s for s in services if s.get("domain") == domain]

    result = []
    for svc in services:
        svc_domain = svc.get("domain", "")
        svc_services = svc.get("services", {})
        for name, details in svc_services.items():
            result.append({
                "service": f"{svc_domain}.{name}",
                "description": details.get("description", ""),
            })

    return json.dumps({"count": len(result), "services": result}, indent=2)


@mcp.tool()
def list_areas() -> str:
    """List all Home Assistant areas with their entities."""
    template = """
{%- set ns = namespace(areas=[]) -%}
{%- for area in areas() -%}
  {%- set entities = area_entities(area) -%}
  {%- set ns.areas = ns.areas + [{"id": area, "name": area_name(area), "entities": entities | length}] -%}
{%- endfor -%}
{{ ns.areas | to_json }}
"""
    raw = _render_template(template.strip())
    try:
        areas = json.loads(raw)
    except json.JSONDecodeError:
        return json.dumps({"error": "Failed to parse areas", "raw": raw[:500]})
    return json.dumps({"count": len(areas), "areas": areas}, indent=2)


@mcp.tool()
def list_devices(area: str = "") -> str:
    """List Home Assistant devices with manufacturer, model, and area.

    Args:
        area: Filter by area name (optional)
    """
    template = """
{%- set ns = namespace(devices=[]) -%}
{%- for state in states -%}
  {%- set did = device_id(state.entity_id) -%}
  {%- if did -%}
    {%- set dname = device_attr(did, 'name') or '' -%}
    {%- set mfr = device_attr(did, 'manufacturer') or '' -%}
    {%- set model = device_attr(did, 'model') or '' -%}
    {%- set darea = area_name(device_attr(did, 'area_id') or '') or '' -%}
    {%- set key = did -%}
    {%- set existing = ns.devices | selectattr('id', 'eq', key) | list -%}
    {%- if existing | length == 0 -%}
      {%- set ns.devices = ns.devices + [{"id": key, "name": dname, "manufacturer": mfr, "model": model, "area": darea}] -%}
    {%- endif -%}
  {%- endif -%}
{%- endfor -%}
{{ ns.devices | to_json }}
"""
    raw = _render_template(template.strip())
    try:
        devices = json.loads(raw)
    except json.JSONDecodeError:
        return json.dumps({"error": "Failed to parse devices", "raw": raw[:500]})

    if area:
        q = area.lower()
        devices = [d for d in devices if q in d.get("area", "").lower()]

    return json.dumps({"count": len(devices), "devices": devices}, indent=2)


# --- Scenes & Scripts ---


@mcp.tool()
def list_scenes() -> str:
    """List all available scenes."""
    with _client() as client:
        resp = client.get("/api/states")
        resp.raise_for_status()
        states = resp.json()

    scenes = [s for s in states if s["entity_id"].startswith("scene.")]
    result = []
    for s in scenes:
        attrs = s.get("attributes", {})
        result.append({
            "entity_id": s["entity_id"],
            "friendly_name": attrs.get("friendly_name", ""),
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def list_scripts() -> str:
    """List all scripts with their current state and last triggered time."""
    with _client() as client:
        resp = client.get("/api/states")
        resp.raise_for_status()
        states = resp.json()

    scripts = [s for s in states if s["entity_id"].startswith("script.")]
    result = []
    for s in scripts:
        attrs = s.get("attributes", {})
        result.append({
            "entity_id": s["entity_id"],
            "state": s["state"],
            "friendly_name": attrs.get("friendly_name", ""),
            "last_triggered": attrs.get("last_triggered"),
        })
    return json.dumps(result, indent=2)


# --- Diagnostics & Analysis ---


@mcp.tool()
def get_logbook(hours: int = 24, entity_id: str = "") -> str:
    """Get the activity logbook (events: who did what, when).

    Different from get_history which tracks state changes.
    The logbook shows actions, triggers, and events.

    Args:
        hours: Number of hours to look back (default: 24)
        entity_id: Filter by entity ID (optional)
    """
    from datetime import datetime, timedelta, timezone

    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    params = {}
    if entity_id:
        params["entity"] = entity_id

    with _client() as client:
        resp = client.get(f"/api/logbook/{start}", params=params)
        resp.raise_for_status()
        logbook = resp.json()

    entries = []
    for entry in logbook[:100]:  # Limit to 100 entries
        entries.append({
            "when": entry.get("when"),
            "name": entry.get("name"),
            "entity_id": entry.get("entity_id"),
            "state": entry.get("state"),
            "message": entry.get("message", ""),
        })
    return json.dumps({
        "hours": hours,
        "count": len(entries),
        "total": len(logbook),
        "entries": entries,
    }, indent=2)


@mcp.tool()
def get_error_log() -> str:
    """Get Home Assistant error log for troubleshooting."""
    with _client() as client:
        resp = client.get("/api/error_log")
        resp.raise_for_status()
        log_text = resp.text

    # Return last 50 lines to keep output manageable
    lines = log_text.strip().split("\n")
    if len(lines) > 50:
        lines = lines[-50:]
        return f"(showing last 50 of {len(log_text.strip().split(chr(10)))} lines)\n" + "\n".join(lines)
    return log_text


@mcp.tool()
def render_template(template: str) -> str:
    """Evaluate a Jinja2 template on Home Assistant.

    Powerful tool for complex queries. Examples:
    - {{ states.light | selectattr('state','eq','on') | map(attribute='entity_id') | list }}
    - {{ states.sensor | selectattr('state','ne','unavailable') | list | count }}
    - {{ area_entities('salon') }}
    - {{ now().strftime('%H:%M') }}
    - {{ state_attr('climate.salon', 'temperature') }}

    Args:
        template: Jinja2 template string to evaluate
    """
    result = _render_template(template)
    return result


@mcp.tool()
def system_health() -> str:
    """Get Home Assistant system health overview: version, integrations, entity counts by domain."""
    with _client() as client:
        resp = client.get("/api/config")
        resp.raise_for_status()
        cfg = resp.json()

        resp2 = client.get("/api/states")
        resp2.raise_for_status()
        states = resp2.json()

    # Count entities by domain
    domain_counts: dict[str, int] = {}
    unavailable_count = 0
    for s in states:
        domain = s["entity_id"].split(".")[0]
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if s.get("state") in ("unavailable", "unknown"):
            unavailable_count += 1

    components = cfg.get("components", [])
    integrations = sorted({c.split(".")[0] for c in components})

    return json.dumps({
        "version": cfg.get("version"),
        "location_name": cfg.get("location_name"),
        "time_zone": cfg.get("time_zone"),
        "integrations_count": len(integrations),
        "total_entities": len(states),
        "unavailable_entities": unavailable_count,
        "entities_by_domain": dict(sorted(domain_counts.items(), key=lambda x: -x[1])),
    }, indent=2)


# --- Calendar ---


@mcp.tool()
def list_calendars() -> str:
    """List all calendar entities."""
    with _client() as client:
        resp = client.get("/api/calendars")
        resp.raise_for_status()
        calendars = resp.json()

    return json.dumps(calendars, indent=2)


@mcp.tool()
def get_calendar_events(entity_id: str, days: int = 7) -> str:
    """Get upcoming events from a calendar.

    Args:
        entity_id: Calendar entity ID (e.g. "calendar.personal")
        days: Number of days to look ahead (default: 7)
    """
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    with _client() as client:
        resp = client.get(
            f"/api/calendars/{entity_id}",
            params={"start": start, "end": end},
        )
        resp.raise_for_status()
        events = resp.json()

    return json.dumps({
        "entity_id": entity_id,
        "days": days,
        "count": len(events),
        "events": events,
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
