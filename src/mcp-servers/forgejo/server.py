"""MCP Server for Forgejo (Gitea-compatible Git forge).

Provides tools to interact with Forgejo via its REST API v1:
- List/search repositories
- Manage issues and pull requests
- Browse branches, commits and file contents
- Create issues and comments

Requires env vars:
  FORGEJO_URL=http://forgejo.forgejo.svc.cluster.local:3000
  FORGEJO_TOKEN=<personal-access-token>
"""

import json
import logging
import os
from base64 import b64decode

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("forgejo")

FORGEJO_URL = os.getenv("FORGEJO_URL", "").rstrip("/")
FORGEJO_TOKEN = os.getenv("FORGEJO_TOKEN", "")


def _client() -> httpx.Client:
    headers = {"Authorization": f"token {FORGEJO_TOKEN}", "Content-Type": "application/json"}
    return httpx.Client(base_url=f"{FORGEJO_URL}/api/v1", headers=headers, timeout=30)


@mcp.tool()
def get_authenticated_user() -> str:
    """Get information about the authenticated user."""
    with _client() as c:
        resp = c.get("/user")
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def list_repos(limit: int = 50, page: int = 1) -> str:
    """List repositories accessible to the authenticated user.

    Args:
        limit: Max results per page (default 50)
        page: Page number (default 1)
    """
    with _client() as c:
        resp = c.get("/repos/search", params={"limit": limit, "page": page, "sort": "updated"})
        resp.raise_for_status()
        data = resp.json()

    repos = [
        {
            "full_name": r["full_name"],
            "description": r.get("description", ""),
            "default_branch": r.get("default_branch", "main"),
            "private": r.get("private", False),
            "open_issues": r.get("open_issues_count", 0),
            "stars": r.get("stars_count", 0),
            "updated": r.get("updated", ""),
            "clone_url": r.get("clone_url", ""),
            "html_url": r.get("html_url", ""),
        }
        for r in data.get("data", [])
    ]
    return json.dumps({"total": data.get("ok", len(repos)), "repos": repos}, indent=2)


@mcp.tool()
def get_repo(owner: str, repo: str) -> str:
    """Get detailed information about a repository.

    Args:
        owner: Repository owner (user or org)
        repo: Repository name
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}")
        resp.raise_for_status()
    r = resp.json()
    return json.dumps({
        "full_name": r["full_name"],
        "description": r.get("description", ""),
        "default_branch": r.get("default_branch", "main"),
        "private": r.get("private", False),
        "open_issues": r.get("open_issues_count", 0),
        "stars": r.get("stars_count", 0),
        "forks": r.get("forks_count", 0),
        "updated": r.get("updated", ""),
        "html_url": r.get("html_url", ""),
        "clone_url": r.get("clone_url", ""),
        "ssh_url": r.get("ssh_url", ""),
    }, indent=2)


@mcp.tool()
def list_branches(owner: str, repo: str) -> str:
    """List branches of a repository.

    Args:
        owner: Repository owner
        repo: Repository name
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/branches", params={"limit": 50})
        resp.raise_for_status()
    branches = [
        {
            "name": b["name"],
            "protected": b.get("protected", False),
            "commit_sha": b.get("commit", {}).get("id", ""),
            "commit_message": b.get("commit", {}).get("message", "").split("\n")[0],
        }
        for b in resp.json()
    ]
    return json.dumps({"count": len(branches), "branches": branches}, indent=2)


@mcp.tool()
def list_commits(owner: str, repo: str, branch: str = "", limit: int = 20) -> str:
    """List recent commits on a branch.

    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch name (default: repo default branch)
        limit: Max commits to return (default 20)
    """
    params = {"limit": limit}
    if branch:
        params["sha"] = branch
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/commits", params=params)
        resp.raise_for_status()
    commits = [
        {
            "sha": c_["sha"][:8],
            "message": c_.get("commit", {}).get("message", "").split("\n")[0],
            "author": c_.get("commit", {}).get("author", {}).get("name", ""),
            "date": c_.get("commit", {}).get("author", {}).get("date", ""),
            "html_url": c_.get("html_url", ""),
        }
        for c_ in resp.json()
    ]
    return json.dumps({"count": len(commits), "commits": commits}, indent=2)


@mcp.tool()
def get_file(owner: str, repo: str, filepath: str, ref: str = "") -> str:
    """Get file content from a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        filepath: Path to file (e.g. src/main.py)
        ref: Branch, tag or commit SHA (default: default branch)
    """
    params = {}
    if ref:
        params["ref"] = ref
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/contents/{filepath}", params=params)
        resp.raise_for_status()
    data = resp.json()
    content_b64 = data.get("content", "")
    content = b64decode(content_b64).decode("utf-8", errors="replace") if content_b64 else ""
    return json.dumps({
        "name": data.get("name", ""),
        "path": data.get("path", ""),
        "sha": data.get("sha", ""),
        "size": data.get("size", 0),
        "encoding": data.get("encoding", ""),
        "content": content,
    }, indent=2)


@mcp.tool()
def list_issues(owner: str, repo: str, state: str = "open", limit: int = 20) -> str:
    """List issues in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        state: "open", "closed" or "all" (default: open)
        limit: Max results (default 20)
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/issues", params={
            "state": state, "type": "issues", "limit": limit
        })
        resp.raise_for_status()
    issues = [
        {
            "number": i["number"],
            "title": i["title"],
            "state": i["state"],
            "author": i.get("user", {}).get("login", ""),
            "labels": [lb["name"] for lb in i.get("labels", [])],
            "created": i.get("created_at", ""),
            "updated": i.get("updated_at", ""),
            "html_url": i.get("html_url", ""),
        }
        for i in resp.json()
    ]
    return json.dumps({"count": len(issues), "state": state, "issues": issues}, indent=2)


@mcp.tool()
def create_issue(owner: str, repo: str, title: str, body: str = "", labels: list = None) -> str:
    """Create a new issue in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        title: Issue title
        body: Issue body (Markdown)
        labels: List of label names
    """
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    with _client() as c:
        resp = c.post(f"/repos/{owner}/{repo}/issues", json=payload)
        resp.raise_for_status()
    i = resp.json()
    return json.dumps({
        "number": i["number"],
        "title": i["title"],
        "html_url": i.get("html_url", ""),
    }, indent=2)


@mcp.tool()
def list_pull_requests(owner: str, repo: str, state: str = "open", limit: int = 20) -> str:
    """List pull requests in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        state: "open", "closed" or "all" (default: open)
        limit: Max results (default 20)
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/pulls", params={"state": state, "limit": limit})
        resp.raise_for_status()
    prs = [
        {
            "number": pr["number"],
            "title": pr["title"],
            "state": pr["state"],
            "author": pr.get("user", {}).get("login", ""),
            "head": pr.get("head", {}).get("label", ""),
            "base": pr.get("base", {}).get("label", ""),
            "mergeable": pr.get("mergeable", None),
            "created": pr.get("created_at", ""),
            "updated": pr.get("updated_at", ""),
            "html_url": pr.get("html_url", ""),
        }
        for pr in resp.json()
    ]
    return json.dumps({"count": len(prs), "state": state, "pull_requests": prs}, indent=2)


@mcp.tool()
def get_pull_request(owner: str, repo: str, index: int) -> str:
    """Get detailed information about a pull request.

    Args:
        owner: Repository owner
        repo: Repository name
        index: PR number
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/pulls/{index}")
        resp.raise_for_status()
    pr = resp.json()
    return json.dumps({
        "number": pr["number"],
        "title": pr["title"],
        "body": pr.get("body", ""),
        "state": pr["state"],
        "author": pr.get("user", {}).get("login", ""),
        "head": pr.get("head", {}).get("label", ""),
        "base": pr.get("base", {}).get("label", ""),
        "mergeable": pr.get("mergeable", None),
        "merged": pr.get("merged", False),
        "created": pr.get("created_at", ""),
        "updated": pr.get("updated_at", ""),
        "html_url": pr.get("html_url", ""),
    }, indent=2)


@mcp.tool()
def add_issue_comment(owner: str, repo: str, index: int, body: str) -> str:
    """Add a comment to an issue or pull request.

    Args:
        owner: Repository owner
        repo: Repository name
        index: Issue or PR number
        body: Comment body (Markdown)
    """
    with _client() as c:
        resp = c.post(f"/repos/{owner}/{repo}/issues/{index}/comments", json={"body": body})
        resp.raise_for_status()
    c_ = resp.json()
    return json.dumps({"id": c_["id"], "html_url": c_.get("html_url", "")}, indent=2)


@mcp.tool()
def list_webhooks(owner: str, repo: str) -> str:
    """List webhooks configured on a repository.

    Args:
        owner: Repository owner
        repo: Repository name
    """
    with _client() as c:
        resp = c.get(f"/repos/{owner}/{repo}/hooks")
        resp.raise_for_status()
    hooks = [
        {
            "id": h["id"],
            "type": h.get("type", ""),
            "url": h.get("config", {}).get("url", ""),
            "events": h.get("events", []),
            "active": h.get("active", False),
        }
        for h in resp.json()
    ]
    return json.dumps({"count": len(hooks), "webhooks": hooks}, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
