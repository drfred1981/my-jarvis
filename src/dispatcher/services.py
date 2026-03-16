"""Service availability detection.

Checks which MCP services have valid configuration (tokens, URLs, kubeconfig)
and provides the list of active services to other components.
"""

import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# Required env vars per service. A service is "configured" if ALL its vars are non-empty.
SERVICE_REQUIREMENTS = {
    "kubernetes": {"type": "kubeconfig"},
    "fluxcd": {"type": "kubeconfig"},
    "kubectl-mcp": {"type": "kubeconfig"},
    "homeassistant": {"type": "env", "vars": ["HA_URL", "HA_TOKEN"]},
    "grafana-prometheus": {"type": "env", "vars": ["PROMETHEUS_URL"]},
    "git": {"type": "env", "vars": ["GIT_REPOS"]},
    "planka": {"type": "env", "vars": ["PLANKA_URL", "PLANKA_USER", "PLANKA_PASSWORD"]},
    "miniflux": {"type": "env", "vars": ["MINIFLUX_URL", "MINIFLUX_API_KEY"]},
    "immich": {"type": "env", "vars": ["IMMICH_URL", "IMMICH_API_KEY"]},
    "karakeep": {"type": "env", "vars": ["KARAKEEP_URL", "KARAKEEP_API_KEY"]},
    "music-assistant": {"type": "env", "vars": ["MUSIC_ASSISTANT_URL"]},
    "synology-router": {"type": "env", "vars": ["SRM_URL", "SRM_USER", "SRM_PASSWORD"]},
    "plex": {"type": "env", "vars": ["PLEX_URL", "PLEX_TOKEN"]},
    "homebox": {"type": "env", "vars": ["HOMEBOX_URL", "HOMEBOX_USER", "HOMEBOX_PASSWORD"]},
    "lubelog": {"type": "env", "vars": ["LUBELOG_URL", "LUBELOG_API_KEY"]},
    "gatus": {"type": "env", "vars": ["GATUS_URL"]},
    "docmost": {"type": "env", "vars": ["DOCMOST_URL"]},
    "mind": {"type": "env", "vars": ["MIND_URL", "MIND_USER", "MIND_PASSWORD"]},
    "alertmanager": {"type": "env", "vars": ["ALERTMANAGER_URL"]},
}

# Monitor check -> required services mapping
MONITOR_CHECK_SERVICES = {
    "cluster-health": ["kubernetes", "grafana-prometheus"],
    "homeassistant": ["homeassistant"],
    "fluxcd-reconciliation": ["fluxcd"],
    "planka-tasks": ["planka"],
    "gatus-services": ["gatus"],
}


def _check_kubeconfig() -> bool:
    """Check if kubeconfig is available."""
    kubeconfig = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
    if os.path.isfile(kubeconfig):
        return True
    # Also check in-cluster config
    return os.path.isfile("/var/run/secrets/kubernetes.io/serviceaccount/token")


def get_available_services() -> dict[str, bool]:
    """Return a dict of service_name -> is_configured."""
    result = {}
    for name, req in SERVICE_REQUIREMENTS.items():
        if req["type"] == "kubeconfig":
            result[name] = _check_kubeconfig()
        elif req["type"] == "env":
            result[name] = all(bool(os.getenv(v, "").strip()) for v in req["vars"])
    return result


def get_active_services() -> list[str]:
    """Return list of configured service names."""
    return [name for name, available in get_available_services().items() if available]


def get_active_mcp_config(base_config_path: str) -> dict:
    """Filter mcp.json to only include configured services."""
    try:
        with open(base_config_path) as f:
            full_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"mcpServers": {}}

    active = get_active_services()
    filtered = {
        name: cfg
        for name, cfg in full_config.get("mcpServers", {}).items()
        if name in active
    }
    return {"mcpServers": filtered}


def get_allowed_tools_string(services: list[str]) -> str:
    """Build the --allowedTools value for active services + Claude built-in tools."""
    builtin = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch"]
    mcp = [f"mcp__{name}__*" for name in services]
    return ",".join(builtin + mcp)


def is_monitor_check_available(check_name: str) -> bool:
    """Check if a monitor check has all its required services configured."""
    required = MONITOR_CHECK_SERVICES.get(check_name, [])
    if not required:
        return True
    active = get_active_services()
    return any(svc in active for svc in required)


def log_service_status():
    """Log which services are available and which are not."""
    status = get_available_services()
    active = [name for name, ok in status.items() if ok]
    inactive = [name for name, ok in status.items() if not ok]

    if active:
        logger.info("MCP services active: %s", ", ".join(active))
    if inactive:
        logger.info("MCP services inactive (missing config): %s", ", ".join(inactive))
