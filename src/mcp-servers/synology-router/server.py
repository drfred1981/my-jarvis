"""MCP Server for Synology Router Manager (SRM).

Provides tools to interact with a Synology Router via its Web API:
- List connected devices (clients)
- Get network traffic and utilization
- Get system info and status
- Manage Wi-Fi settings
- Check WAN status

Requires env vars:
  SRM_URL=https://router.local:8001
  SRM_USER=admin
  SRM_PASSWORD=secret
"""

import json
import logging
import os
import threading
import time

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("synology-router")

SRM_URL = os.getenv("SRM_URL", "").rstrip("/")
SRM_USER = os.getenv("SRM_USER", "")
SRM_PASSWORD = os.getenv("SRM_PASSWORD", "")

# Session management
_sid: str = ""
_sid_lock = threading.Lock()


def _login() -> str:
    """Authenticate to SRM and return session ID."""
    global _sid
    with httpx.Client(verify=False, timeout=15) as client:
        resp = client.get(
            f"{SRM_URL}/webapi/auth.cgi",
            params={
                "api": "SYNO.API.Auth",
                "method": "Login",
                "version": 2,
                "account": SRM_USER,
                "passwd": SRM_PASSWORD,
                "session": "SRM",
                "format": "sid",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"SRM login failed: {data}")
    _sid = data["data"]["sid"]
    return _sid


def _get_sid() -> str:
    """Get a valid session ID, logging in if needed."""
    global _sid
    with _sid_lock:
        if not _sid:
            _login()
        return _sid


def _call_api(api: str, method: str, version: int = 1, extra_params: dict | None = None) -> dict:
    """Call a SRM API endpoint with automatic re-auth on session expiry."""
    sid = _get_sid()
    params = {
        "api": api,
        "method": method,
        "version": version,
        "_sid": sid,
    }
    if extra_params:
        params.update(extra_params)

    with httpx.Client(verify=False, timeout=30) as client:
        resp = client.get(f"{SRM_URL}/webapi/entry.cgi", params=params)
        resp.raise_for_status()
        data = resp.json()

    # Re-auth on session expiry (error 119 = SID not found)
    if not data.get("success") and data.get("error", {}).get("code") == 119:
        with _sid_lock:
            _login()
        params["_sid"] = _sid
        with httpx.Client(verify=False, timeout=30) as client:
            resp = client.get(f"{SRM_URL}/webapi/entry.cgi", params=params)
            resp.raise_for_status()
            data = resp.json()

    if not data.get("success"):
        raise RuntimeError(f"SRM API error: {api}.{method} -> {data}")

    return data.get("data", {})


@mcp.tool()
def get_system_info() -> str:
    """Get Synology Router system information (model, firmware, uptime)."""
    data = _call_api("SYNO.Core.System", "info", version=1)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_utilization() -> str:
    """Get router resource utilization (CPU, RAM, network throughput)."""
    data = _call_api("SYNO.Core.System.Utilization", "get", version=1)
    result = {}
    if "cpu" in data:
        cpu = data["cpu"]
        result["cpu_percent"] = 100 - cpu.get("idle_load", 0)
    if "memory" in data:
        mem = data["memory"]
        total = mem.get("total_real", 1)
        avail = mem.get("avail_real", 0)
        result["memory_total_mb"] = round(total / 1024, 1)
        result["memory_used_mb"] = round((total - avail) / 1024, 1)
        result["memory_percent"] = round((total - avail) / total * 100, 1)
    if "network" in data:
        result["network"] = data["network"]
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def list_devices() -> str:
    """List all devices connected to the router (IP, MAC, hostname, connection type)."""
    data = _call_api("SYNO.Core.Network.NSM.Device", "get", version=1)
    devices = data.get("devices", [])
    result = []
    for d in devices:
        result.append({
            "hostname": d.get("hostname", ""),
            "ip": d.get("ip", ""),
            "mac": d.get("mac", ""),
            "online": d.get("is_online", False),
            "connection": d.get("connection", ""),
            "band": d.get("band", ""),
            "rate_download": d.get("cur_download", 0),
            "rate_upload": d.get("cur_upload", 0),
        })
    online = sum(1 for d in result if d["online"])
    return json.dumps({"total": len(result), "online": online, "devices": result}, indent=2)


@mcp.tool()
def get_traffic(interval: str = "live") -> str:
    """Get network traffic statistics.

    Args:
        interval: "live" for real-time, "day" for daily, "week" for weekly, "month" for monthly
    """
    data = _call_api(
        "SYNO.Core.Network.Router.TrafficControl.Traffic",
        "get",
        version=1,
        extra_params={"interval": interval},
    )
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_wifi_status() -> str:
    """Get Wi-Fi network status (SSIDs, channels, connected clients)."""
    data = _call_api("SYNO.Wifi.Network.Setting", "get", version=1)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_wan_status() -> str:
    """Get WAN (internet) connection status."""
    data = _call_api("SYNO.Core.Network.Router.Gateway.List", "get", version=1)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_dhcp_clients() -> str:
    """Get DHCP leases (static and dynamic reservations)."""
    data = _call_api("SYNO.Core.Network.DHCP.Server", "get", version=1)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_port_forwarding() -> str:
    """Get port forwarding rules configured on the router."""
    data = _call_api("SYNO.Core.Network.Router.PortForward", "get", version=1)
    return json.dumps(data, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
