"""MCP Server for Gatus (health checks / status page).

Provides tools to interact with Gatus via its REST API:
- List all monitored endpoints with current status
- Get detailed status and results for specific endpoints
- Query uptime percentages and response time metrics
- View response time history

Requires env vars:
  GATUS_URL=http://gatus.local:8080
  GATUS_USER=admin        (optional, for protected endpoints)
  GATUS_PASSWORD=secret   (optional, for protected endpoints)
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("gatus")

GATUS_URL = os.getenv("GATUS_URL", "").rstrip("/")
GATUS_USER = os.getenv("GATUS_USER", "")
GATUS_PASSWORD = os.getenv("GATUS_PASSWORD", "")


def _client() -> httpx.Client:
    auth = (GATUS_USER, GATUS_PASSWORD) if GATUS_USER else None
    return httpx.Client(base_url=GATUS_URL, auth=auth, timeout=30)


def _ns_to_ms(ns) -> float:
    """Convert nanoseconds to milliseconds."""
    try:
        return round(int(ns) / 1_000_000, 1)
    except (ValueError, TypeError):
        return 0


@mcp.tool()
def list_endpoints() -> str:
    """List all monitored endpoints with their current status (up/down, uptime, response time)."""
    with _client() as client:
        resp = client.get("/api/v1/endpoints/statuses")
        resp.raise_for_status()
        data = resp.json()

    endpoints = []
    for ep in data:
        name = ep.get("name", "")
        group = ep.get("group", "")
        key = ep.get("key", "")
        results = ep.get("results", [])

        # Latest result
        latest = results[-1] if results else {}
        success = latest.get("success", None)
        status_code = latest.get("status", 0)
        duration_ms = _ns_to_ms(latest.get("duration", 0))

        # Count recent successes/failures
        recent = results[-10:] if results else []
        ok_count = sum(1 for r in recent if r.get("success"))
        fail_count = len(recent) - ok_count

        endpoints.append({
            "name": name,
            "group": group,
            "key": key,
            "status": "up" if success else ("down" if success is False else "unknown"),
            "http_status": status_code,
            "response_ms": duration_ms,
            "last_check": latest.get("timestamp", ""),
            "recent_10": f"{ok_count} ok / {fail_count} fail",
        })

    # Sort: down first, then by group/name
    endpoints.sort(key=lambda e: (0 if e["status"] == "down" else 1, e["group"], e["name"]))

    up = sum(1 for e in endpoints if e["status"] == "up")
    down = sum(1 for e in endpoints if e["status"] == "down")

    return json.dumps({
        "total": len(endpoints),
        "up": up,
        "down": down,
        "endpoints": endpoints,
    }, indent=2)


@mcp.tool()
def get_endpoint_status(key: str) -> str:
    """Get detailed status and recent results for a specific endpoint.

    Args:
        key: Endpoint key (format: group_endpoint-name, from list_endpoints)
    """
    with _client() as client:
        resp = client.get(f"/api/v1/endpoints/{key}/statuses")
        resp.raise_for_status()
        ep = resp.json()

    name = ep.get("name", "")
    group = ep.get("group", "")
    results = ep.get("results", [])

    formatted_results = []
    for r in results[-20:]:  # Last 20 checks
        entry = {
            "success": r.get("success"),
            "status": r.get("status", 0),
            "response_ms": _ns_to_ms(r.get("duration", 0)),
            "timestamp": r.get("timestamp", ""),
        }
        # Add condition details if present
        conditions = r.get("conditionResults", [])
        if conditions:
            entry["conditions"] = [
                {"condition": c.get("condition", ""), "ok": c.get("success", False)}
                for c in conditions
            ]
        # Add errors
        errors = r.get("errors", [])
        if errors:
            entry["errors"] = errors
        formatted_results.append(entry)

    return json.dumps({
        "name": name,
        "group": group,
        "key": key,
        "total_results": len(results),
        "results": formatted_results,
    }, indent=2)


@mcp.tool()
def get_uptime(key: str, duration: str = "7d") -> str:
    """Get uptime percentage for an endpoint.

    Args:
        key: Endpoint key (from list_endpoints)
        duration: Time period - "1h", "24h", "7d", or "30d" (default: 7d)
    """
    with _client() as client:
        resp = client.get(f"/api/v1/endpoints/{key}/uptimes/{duration}")
        resp.raise_for_status()
        uptime = resp.text.strip()

    return json.dumps({
        "key": key,
        "duration": duration,
        "uptime_percent": float(uptime),
    }, indent=2)


@mcp.tool()
def get_response_times(key: str, duration: str = "24h") -> str:
    """Get response time statistics for an endpoint.

    Args:
        key: Endpoint key (from list_endpoints)
        duration: Time period - "1h", "24h", "7d", or "30d" (default: 24h)
    """
    with _client() as client:
        resp = client.get(f"/api/v1/endpoints/{key}/response-times/{duration}")
        resp.raise_for_status()
        avg_ns = resp.text.strip()

    return json.dumps({
        "key": key,
        "duration": duration,
        "avg_response_ms": _ns_to_ms(avg_ns),
    }, indent=2)


@mcp.tool()
def get_response_history(key: str, duration: str = "24h") -> str:
    """Get response time history for trend analysis.

    Args:
        key: Endpoint key (from list_endpoints)
        duration: Time period - "1h", "24h", "7d", or "30d" (default: 24h)
    """
    with _client() as client:
        resp = client.get(f"/api/v1/endpoints/{key}/response-times/{duration}/history")
        resp.raise_for_status()
        data = resp.json()

    return json.dumps({
        "key": key,
        "duration": duration,
        "history": data,
    }, indent=2, default=str)


@mcp.tool()
def get_all_uptimes(duration: str = "24h") -> str:
    """Get uptime summary for ALL endpoints at once.

    Args:
        duration: Time period - "1h", "24h", "7d", or "30d" (default: 24h)
    """
    with _client() as client:
        resp = client.get("/api/v1/endpoints/statuses")
        resp.raise_for_status()
        data = resp.json()

    results = []
    for ep in data:
        key = ep.get("key", "")
        name = ep.get("name", "")
        group = ep.get("group", "")

        try:
            resp_uptime = client.get(f"/api/v1/endpoints/{key}/uptimes/{duration}")
            uptime = float(resp_uptime.text.strip()) if resp_uptime.status_code == 200 else None
        except Exception:
            uptime = None

        results.append({
            "name": name,
            "group": group,
            "key": key,
            "uptime_percent": uptime,
        })

    # Sort by uptime (worst first)
    results.sort(key=lambda r: r["uptime_percent"] if r["uptime_percent"] is not None else 999)

    degraded = [r for r in results if r["uptime_percent"] is not None and r["uptime_percent"] < 100]

    return json.dumps({
        "duration": duration,
        "total": len(results),
        "degraded": len(degraded),
        "endpoints": results,
    }, indent=2)


@mcp.tool()
def get_health() -> str:
    """Get Gatus server health status."""
    with _client() as client:
        resp = client.get("/health")
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
