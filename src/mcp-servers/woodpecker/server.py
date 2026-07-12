"""MCP Server for Woodpecker CI.

Provides tools to interact with Woodpecker CI via its REST API v1:
- List enabled repositories
- View and trigger pipelines
- Browse pipeline steps and retrieve logs
- Check pipeline status

Requires env vars:
  WOODPECKER_URL=http://woodpecker.woodpecker.svc.cluster.local:8000
  WOODPECKER_TOKEN=<api-token>
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("woodpecker")

WOODPECKER_URL = os.getenv("WOODPECKER_URL", "").rstrip("/")
WOODPECKER_TOKEN = os.getenv("WOODPECKER_TOKEN", "")


def _client() -> httpx.Client:
    headers = {"Authorization": f"Bearer {WOODPECKER_TOKEN}"}
    return httpx.Client(base_url=f"{WOODPECKER_URL}/api", headers=headers, timeout=30)


def _fmt_pipeline(p: dict) -> dict:
    return {
        "number": p.get("number"),
        "status": p.get("status"),
        "event": p.get("event"),
        "branch": p.get("branch"),
        "commit": p.get("commit", "")[:8],
        "message": (p.get("message") or "").split("\n")[0],
        "author": p.get("author"),
        "started": p.get("started"),
        "finished": p.get("finished"),
        "link": p.get("link_url"),
    }


@mcp.tool()
def list_repos() -> str:
    """List all repositories enabled in Woodpecker CI."""
    with _client() as c:
        resp = c.get("/repos")
        resp.raise_for_status()
    repos = [
        {
            "id": r.get("id"),
            "full_name": r.get("full_name"),
            "active": r.get("active", False),
            "private": r.get("private", False),
            "link": r.get("link_url", ""),
            "timeout": r.get("timeout", 60),
        }
        for r in resp.json()
    ]
    return json.dumps({"count": len(repos), "repos": repos}, indent=2)


@mcp.tool()
def list_pipelines(owner: str, repo: str, page: int = 1, per_page: int = 20) -> str:
    """List recent pipelines for a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        page: Page number (default 1)
        per_page: Results per page (default 20)
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/pipelines", params={"page": page, "perPage": per_page})
        resp.raise_for_status()
    pipelines = [_fmt_pipeline(p) for p in resp.json()]
    return json.dumps({"count": len(pipelines), "page": page, "pipelines": pipelines}, indent=2)


@mcp.tool()
def get_pipeline(owner: str, repo: str, pipeline_number: int) -> str:
    """Get detailed information about a specific pipeline including its steps.

    Args:
        owner: Repository owner
        repo: Repository name
        pipeline_number: Pipeline number (from list_pipelines)
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/pipelines/{pipeline_number}")
        resp.raise_for_status()
    p = resp.json()
    steps = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "status": s.get("state"),
            "started": s.get("started"),
            "stopped": s.get("stopped"),
            "exit_code": s.get("exit_code"),
        }
        for s in p.get("steps", [])
    ]
    result = _fmt_pipeline(p)
    result["steps"] = steps
    result["errors"] = p.get("errors")
    return json.dumps(result, indent=2)


@mcp.tool()
def get_step_logs(owner: str, repo: str, pipeline_number: int, step_id: int) -> str:
    """Get logs for a specific pipeline step.

    Args:
        owner: Repository owner
        repo: Repository name
        pipeline_number: Pipeline number
        step_id: Step ID (from get_pipeline steps list)
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/pipelines/{pipeline_number}/steps/{step_id}/logs")
        resp.raise_for_status()
    logs = resp.json()
    lines = [entry.get("data", "") for entry in (logs if isinstance(logs, list) else [])]
    return json.dumps({
        "owner": owner,
        "repo": repo,
        "pipeline": pipeline_number,
        "step_id": step_id,
        "log": "".join(lines),
    }, indent=2)


@mcp.tool()
def trigger_pipeline(owner: str, repo: str, branch: str = "") -> str:
    """Trigger (restart) the latest pipeline on a branch, or create a new one.

    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch to trigger (default: repo default branch)
    """
    with _client() as c:
        # Get latest pipeline number for this branch
        params = {"page": 1, "perPage": 1}
        resp = c.get(f"/repos/{owner}/{repo}/pipelines", params=params)
        resp.raise_for_status()
        pipelines = resp.json()

    if not pipelines:
        return json.dumps({"error": "No existing pipeline found to restart"})

    latest = pipelines[0]
    number = latest["number"]

    with _client() as c:
        resp = c.post(f"/repos/{owner}/{repo}/pipelines/{number}")
        resp.raise_for_status()
    p = resp.json()
    return json.dumps({
        "triggered": True,
        "new_pipeline": _fmt_pipeline(p),
    }, indent=2)


@mcp.tool()
def get_repo_info(owner: str, repo: str) -> str:
    """Get Woodpecker configuration for a specific repository.

    Args:
        owner: Repository owner
        repo: Repository name
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}")
        resp.raise_for_status()
    r = resp.json()
    return json.dumps({
        "id": r.get("id"),
        "full_name": r.get("full_name"),
        "active": r.get("active", False),
        "private": r.get("private", False),
        "timeout": r.get("timeout", 60),
        "visibility": r.get("visibility", ""),
        "cancel_previous_pipeline_events": r.get("cancel_previous_pipeline_events", []),
        "link": r.get("link_url", ""),
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
