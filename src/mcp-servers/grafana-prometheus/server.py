"""MCP Server for Grafana and Prometheus.

Provides tools to query metrics from Prometheus and interact with Grafana:
- Execute PromQL queries
- List and get Grafana dashboards
- Check alerting rules and active alerts
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("grafana-prometheus")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.monitoring.svc.cluster.local:9090")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://grafana.monitoring.svc.cluster.local:3000")
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN", "")


def _prom_client() -> httpx.Client:
    return httpx.Client(base_url=PROMETHEUS_URL, timeout=30)


def _grafana_client() -> httpx.Client:
    headers = {}
    if GRAFANA_TOKEN:
        headers["Authorization"] = f"Bearer {GRAFANA_TOKEN}"
    return httpx.Client(base_url=GRAFANA_URL, headers=headers, timeout=30)


# --- Prometheus ---

@mcp.tool()
def prometheus_query(query: str) -> str:
    """Execute an instant PromQL query.

    Args:
        query: PromQL expression (e.g. 'up', 'node_cpu_seconds_total{mode="idle"}')
    """
    with _prom_client() as client:
        resp = client.get("/api/v1/query", params={"query": query})
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "success":
        return f"Query failed: {data.get('error', 'unknown error')}"

    results = data.get("data", {}).get("result", [])
    formatted = []
    for r in results:
        formatted.append({
            "metric": r.get("metric", {}),
            "value": r.get("value", [None, None])[1],
        })
    return json.dumps(formatted, indent=2)


@mcp.tool()
def prometheus_query_range(query: str, start: str = "", end: str = "", step: str = "60s") -> str:
    """Execute a range PromQL query.

    Args:
        query: PromQL expression
        start: Start time (RFC3339 or Unix timestamp). Default: 1 hour ago
        end: End time (RFC3339 or Unix timestamp). Default: now
        step: Query resolution step (e.g. "60s", "5m")
    """
    from datetime import datetime, timedelta, timezone

    params = {"query": query, "step": step}
    if not end:
        params["end"] = datetime.now(timezone.utc).isoformat()
    else:
        params["end"] = end
    if not start:
        params["start"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    else:
        params["start"] = start

    with _prom_client() as client:
        resp = client.get("/api/v1/query_range", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "success":
        return f"Query failed: {data.get('error', 'unknown error')}"

    results = data.get("data", {}).get("result", [])
    formatted = []
    for r in results:
        values = r.get("values", [])
        formatted.append({
            "metric": r.get("metric", {}),
            "samples": len(values),
            "first_value": values[0][1] if values else None,
            "last_value": values[-1][1] if values else None,
        })
    return json.dumps(formatted, indent=2)


@mcp.tool()
def prometheus_alerts() -> str:
    """Get all active Prometheus alerts."""
    with _prom_client() as client:
        resp = client.get("/api/v1/alerts")
        resp.raise_for_status()
        data = resp.json()

    alerts = data.get("data", {}).get("alerts", [])
    result = []
    for a in alerts:
        result.append({
            "alertname": a.get("labels", {}).get("alertname", ""),
            "state": a.get("state", ""),
            "severity": a.get("labels", {}).get("severity", ""),
            "summary": a.get("annotations", {}).get("summary", ""),
            "active_at": a.get("activeAt", ""),
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def prometheus_rules() -> str:
    """Get all Prometheus alerting and recording rules."""
    with _prom_client() as client:
        resp = client.get("/api/v1/rules")
        resp.raise_for_status()
        data = resp.json()

    groups = data.get("data", {}).get("groups", [])
    result = []
    for g in groups:
        rules = []
        for r in g.get("rules", []):
            rules.append({
                "name": r.get("name"),
                "type": r.get("type"),
                "state": r.get("state", ""),
                "health": r.get("health", ""),
                "query": r.get("query", ""),
            })
        result.append({
            "group": g.get("name"),
            "file": g.get("file"),
            "rules": rules,
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def prometheus_targets() -> str:
    """Get all Prometheus scrape targets and their status."""
    with _prom_client() as client:
        resp = client.get("/api/v1/targets")
        resp.raise_for_status()
        data = resp.json()

    active = data.get("data", {}).get("activeTargets", [])
    result = []
    for t in active:
        result.append({
            "job": t.get("labels", {}).get("job", ""),
            "instance": t.get("labels", {}).get("instance", ""),
            "health": t.get("health", ""),
            "last_scrape": t.get("lastScrape", ""),
            "scrape_duration": t.get("lastScrapeDuration", 0),
        })
    return json.dumps(result, indent=2)


# --- Grafana ---

@mcp.tool()
def grafana_list_dashboards(query: str = "") -> str:
    """List Grafana dashboards, optionally filtered by search query.

    Args:
        query: Search query to filter dashboards
    """
    with _grafana_client() as client:
        params = {"type": "dash-db"}
        if query:
            params["query"] = query
        resp = client.get("/api/search", params=params)
        resp.raise_for_status()
        dashboards = resp.json()

    result = []
    for d in dashboards:
        result.append({
            "uid": d.get("uid"),
            "title": d.get("title"),
            "url": d.get("url"),
            "tags": d.get("tags", []),
            "folder": d.get("folderTitle", ""),
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def grafana_get_dashboard(uid: str) -> str:
    """Get a Grafana dashboard by UID.

    Args:
        uid: Dashboard UID
    """
    with _grafana_client() as client:
        resp = client.get(f"/api/dashboards/uid/{uid}")
        resp.raise_for_status()
        data = resp.json()

    dashboard = data.get("dashboard", {})
    panels = []
    for p in dashboard.get("panels", []):
        panel_info = {
            "id": p.get("id"),
            "title": p.get("title"),
            "type": p.get("type"),
        }
        # Extract targets/queries if present
        targets = p.get("targets", [])
        if targets:
            panel_info["queries"] = [t.get("expr", t.get("rawSql", "")) for t in targets]
        panels.append(panel_info)

    return json.dumps({
        "title": dashboard.get("title"),
        "uid": dashboard.get("uid"),
        "tags": dashboard.get("tags", []),
        "panels": panels,
    }, indent=2)


@mcp.tool()
def grafana_alerts() -> str:
    """Get active Grafana alerting rules."""
    with _grafana_client() as client:
        resp = client.get("/api/v1/provisioning/alert-rules")
        resp.raise_for_status()
        rules = resp.json()

    result = []
    for r in rules:
        result.append({
            "title": r.get("title"),
            "uid": r.get("uid"),
            "condition": r.get("condition"),
            "folder_uid": r.get("folderUID"),
            "is_paused": r.get("isPaused", False),
        })
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
