"""MCP Server for Woodpecker CI.

Provides tools to interact with Woodpecker CI via its REST API:
- List activated repositories
- List and inspect pipelines
- Get pipeline step logs
- Trigger and restart pipelines
- Pause/resume CI for a repository

Requires env vars:
  WOODPECKER_URL=http://woodpecker.woodpecker.svc.cluster.local:80
  WOODPECKER_TOKEN=<personal-access-token>
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
    return httpx.Client(
        base_url=WOODPECKER_URL + "/api",
        headers={"Authorization": f"Bearer {WOODPECKER_TOKEN}"},
        timeout=30,
    )


@mcp.tool()
def list_repos(all_repos: bool = False) -> str:
    """List repositories activated in Woodpecker CI.

    Args:
        all_repos: If True, list all repos (admin only). Default: only own repos.
    """
    with _client() as c:
        params = {"all": "true"} if all_repos else {}
        r = c.get("/repos", params=params)
        r.raise_for_status()
        repos = r.json()
    return json.dumps([{
        "id": repo.get("id"),
        "full_name": repo.get("full_name", ""),
        "owner": repo.get("owner", ""),
        "name": repo.get("name", ""),
        "active": repo.get("active", False),
        "allow_pr": repo.get("allow_pr", False),
        "timeout": repo.get("timeout", 0),
        "visibility": repo.get("visibility", ""),
        "default_branch": repo.get("default_branch", ""),
    } for repo in (repos if isinstance(repos, list) else [])], indent=2)


@mcp.tool()
def list_pipelines(owner: str, repo: str, limit: int = 20) -> str:
    """List pipelines for a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        limit: Max results (default 20)
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/pipelines", params={"per_page": limit})
        r.raise_for_status()
        pipelines = r.json()

    return json.dumps([{
        "number": p.get("number"),
        "status": p.get("status", ""),
        "event": p.get("event", ""),
        "branch": p.get("branch", ""),
        "commit": (p.get("commit") or "")[:8],
        "message": (p.get("message") or "")[:100],
        "author": p.get("author", ""),
        "created": p.get("created", 0),
        "started": p.get("started", 0),
        "finished": p.get("finished", 0),
        "duration_s": (p.get("finished", 0) or 0) - (p.get("started", 0) or 0),
    } for p in (pipelines if isinstance(pipelines, list) else [])], indent=2)


@mcp.tool()
def get_pipeline(owner: str, repo: str, pipeline_number: int) -> str:
    """Get details of a specific pipeline including all steps.

    Args:
        owner: Repository owner
        repo: Repository name
        pipeline_number: Pipeline number
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/pipelines/{pipeline_number}")
        r.raise_for_status()
        p = r.json()

    steps = []
    for stage in p.get("stages", []):
        for step in stage.get("steps", []):
            steps.append({
                "stage": stage.get("name", ""),
                "step_id": step.get("id"),
                "name": step.get("name", ""),
                "status": step.get("state", ""),
                "exit_code": step.get("exit_code", 0),
                "started": step.get("started", 0),
                "stopped": step.get("stopped", 0),
                "duration_s": (step.get("stopped", 0) or 0) - (step.get("started", 0) or 0),
            })

    return json.dumps({
        "number": p.get("number"),
        "status": p.get("status", ""),
        "event": p.get("event", ""),
        "branch": p.get("branch", ""),
        "commit": (p.get("commit") or "")[:8],
        "message": p.get("message", ""),
        "author": p.get("author", ""),
        "started": p.get("started", 0),
        "finished": p.get("finished", 0),
        "steps": steps,
    }, indent=2)


@mcp.tool()
def get_step_logs(owner: str, repo: str, pipeline_number: int, step_id: int) -> str:
    """Get logs for a specific pipeline step.

    Args:
        owner: Repository owner
        repo: Repository name
        pipeline_number: Pipeline number
        step_id: Step ID (from get_pipeline steps[].step_id)
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/logs/{pipeline_number}/{step_id}")
        r.raise_for_status()
        log_entries = r.json()

    lines = [entry.get("data", "") for entry in (log_entries if isinstance(log_entries, list) else [])]
    return json.dumps({
        "owner": owner,
        "repo": repo,
        "pipeline": pipeline_number,
        "step_id": step_id,
        "log": "".join(lines),
    }, indent=2)


@mcp.tool()
def restart_pipeline(owner: str, repo: str, pipeline_number: int) -> str:
    """Restart (re-run) a pipeline.

    Args:
        owner: Repository owner
        repo: Repository name
        pipeline_number: Pipeline number to restart
    """
    with _client() as c:
        r = c.post(f"/repos/{owner}/{repo}/pipelines/{pipeline_number}")
        r.raise_for_status()
        p = r.json()
    return json.dumps({
        "new_number": p.get("number"),
        "status": p.get("status", ""),
        "created": p.get("created", 0),
    }, indent=2)


@mcp.tool()
def cancel_pipeline(owner: str, repo: str, pipeline_number: int) -> str:
    """Cancel a running pipeline.

    Args:
        owner: Repository owner
        repo: Repository name
        pipeline_number: Pipeline number to cancel
    """
    with _client() as c:
        r = c.delete(f"/repos/{owner}/{repo}/pipelines/{pipeline_number}")
        r.raise_for_status()
    return json.dumps({"cancelled": True, "pipeline": pipeline_number}, indent=2)


@mcp.tool()
def get_repo_info(owner: str, repo: str) -> str:
    """Get Woodpecker CI configuration for a specific repository.

    Args:
        owner: Repository owner
        repo: Repository name
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}")
        r.raise_for_status()
        data = r.json()
    return json.dumps({
        "id": data.get("id"),
        "full_name": data.get("full_name", ""),
        "active": data.get("active", False),
        "allow_pr": data.get("allow_pr", False),
        "timeout": data.get("timeout", 0),
        "visibility": data.get("visibility", ""),
        "config_file": data.get("config_file", ".woodpecker.yml"),
        "cancel_previous_pipeline_on_push": data.get("cancel_previous_pipeline_on_push", False),
    }, indent=2)


@mcp.tool()
def get_woodpecker_info() -> str:
    """Get Woodpecker server version and info."""
    with _client() as c:
        r = c.get("/version")
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
