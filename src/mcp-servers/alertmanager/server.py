"""MCP Server for Alertmanager.

Provides tools to interact with Alertmanager:
- List active alerts and their status
- Get alert groups
- List silences (active, expired, pending)
- Create and delete silences
- Get Alertmanager status and cluster info
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("alertmanager")

ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "")


def _client() -> httpx.Client:
    return httpx.Client(base_url=ALERTMANAGER_URL, timeout=30)


@mcp.tool()
def get_alerts(filter: str = "", silenced: bool = False, inhibited: bool = False, active: bool = True, unprocessed: bool = False) -> str:
    """Get current alerts from Alertmanager.

    Args:
        filter: PromQL-style matcher filter (e.g. 'alertname=Watchdog', 'severity=~critical|warning')
        silenced: Include silenced alerts
        inhibited: Include inhibited alerts
        active: Include active (firing) alerts
        unprocessed: Include unprocessed alerts
    """
    params = {
        "silenced": str(silenced).lower(),
        "inhibited": str(inhibited).lower(),
        "active": str(active).lower(),
        "unprocessed": str(unprocessed).lower(),
    }
    if filter:
        params["filter"] = filter

    with _client() as client:
        resp = client.get("/api/v2/alerts", params=params)
        resp.raise_for_status()
        alerts = resp.json()

    result = []
    for a in alerts:
        labels = a.get("labels", {})
        annotations = a.get("annotations", {})
        status = a.get("status", {})
        result.append({
            "alertname": labels.get("alertname", ""),
            "severity": labels.get("severity", ""),
            "namespace": labels.get("namespace", ""),
            "state": status.get("state", ""),
            "silenced_by": status.get("silencedBy", []),
            "inhibited_by": status.get("inhibitedBy", []),
            "summary": annotations.get("summary", ""),
            "description": annotations.get("description", ""),
            "starts_at": a.get("startsAt", ""),
            "ends_at": a.get("endsAt", ""),
            "generator_url": a.get("generatorURL", ""),
            "labels": labels,
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_alert_groups() -> str:
    """Get alerts grouped by their grouping labels."""
    with _client() as client:
        resp = client.get("/api/v2/alerts/groups")
        resp.raise_for_status()
        groups = resp.json()

    result = []
    for g in groups:
        receiver = g.get("receiver", {})
        alerts = []
        for a in g.get("alerts", []):
            labels = a.get("labels", {})
            alerts.append({
                "alertname": labels.get("alertname", ""),
                "severity": labels.get("severity", ""),
                "state": a.get("status", {}).get("state", ""),
                "starts_at": a.get("startsAt", ""),
            })
        result.append({
            "receiver": receiver.get("name", ""),
            "group_labels": g.get("labels", {}),
            "alert_count": len(alerts),
            "alerts": alerts,
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def list_silences(state: str = "") -> str:
    """List all silences in Alertmanager.

    Args:
        state: Filter by state: 'active', 'pending', or 'expired' (empty for all)
    """
    with _client() as client:
        resp = client.get("/api/v2/silences")
        resp.raise_for_status()
        silences = resp.json()

    result = []
    for s in silences:
        s_state = s.get("status", {}).get("state", "")
        if state and s_state != state:
            continue
        matchers = []
        for m in s.get("matchers", []):
            op = "=~" if m.get("isRegex") else ("!=" if m.get("isEqual") is False else "=")
            matchers.append(f"{m.get('name', '')}{op}{m.get('value', '')}")
        result.append({
            "id": s.get("id", ""),
            "state": s_state,
            "matchers": matchers,
            "comment": s.get("comment", ""),
            "created_by": s.get("createdBy", ""),
            "starts_at": s.get("startsAt", ""),
            "ends_at": s.get("endsAt", ""),
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def create_silence(matchers: str, comment: str, duration_hours: int = 4, created_by: str = "jarvis") -> str:
    """Create a silence in Alertmanager.

    Args:
        matchers: JSON array of matchers, e.g. '[{"name":"alertname","value":"Watchdog","isRegex":false}]'
        comment: Reason for the silence
        duration_hours: Duration in hours (default: 4)
        created_by: Author of the silence (default: jarvis)
    """
    now = datetime.now(timezone.utc)
    ends_at = now + timedelta(hours=duration_hours)

    try:
        parsed_matchers = json.loads(matchers)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid matchers JSON"})

    for m in parsed_matchers:
        m.setdefault("isRegex", False)
        m.setdefault("isEqual", True)

    payload = {
        "matchers": parsed_matchers,
        "startsAt": now.isoformat(),
        "endsAt": ends_at.isoformat(),
        "createdBy": created_by,
        "comment": comment,
    }

    with _client() as client:
        resp = client.post("/api/v2/silences", json=payload)
        resp.raise_for_status()
        data = resp.json()

    return json.dumps({"silenceID": data.get("silenceID", ""), "status": "created", "ends_at": ends_at.isoformat()}, indent=2)


@mcp.tool()
def delete_silence(silence_id: str) -> str:
    """Delete (expire) a silence by ID.

    Args:
        silence_id: The silence ID to expire
    """
    with _client() as client:
        resp = client.delete(f"/api/v2/silence/{silence_id}")
        resp.raise_for_status()

    return json.dumps({"status": "expired", "silence_id": silence_id})


@mcp.tool()
def get_status() -> str:
    """Get Alertmanager status including version, uptime, and cluster info."""
    with _client() as client:
        resp = client.get("/api/v2/status")
        resp.raise_for_status()
        data = resp.json()

    cluster = data.get("cluster", {})
    version_info = data.get("versionInfo", {})

    return json.dumps({
        "uptime": data.get("uptime", ""),
        "version": version_info.get("version", ""),
        "cluster_status": cluster.get("status", ""),
        "cluster_peers": len(cluster.get("peers", [])),
    }, indent=2)


@mcp.tool()
def get_receivers() -> str:
    """List all configured receivers in Alertmanager."""
    with _client() as client:
        resp = client.get("/api/v2/receivers")
        resp.raise_for_status()
        receivers = resp.json()

    result = [{"name": r.get("name", "")} for r in receivers]
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
