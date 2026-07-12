"""MCP Server for Forgejo (self-hosted Git).

Provides tools to interact with Forgejo (Gitea-compatible) via its REST API:
- Search and browse repositories
- List/create issues and pull requests
- Comment on issues/PRs
- Browse branches, releases, and file content
- Get current user info

Requires env vars:
  FORGEJO_URL=http://forgejo.forgejo.svc.cluster.local:3000
  FORGEJO_TOKEN=<personal-access-token>

Optional:
  FORGEJO_USER=<username>  (for basic auth instead of token)
  FORGEJO_PASSWORD=<pass>
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("forgejo")

FORGEJO_URL = os.getenv("FORGEJO_URL", "").rstrip("/")
FORGEJO_TOKEN = os.getenv("FORGEJO_TOKEN", "")
FORGEJO_USER = os.getenv("FORGEJO_USER", "")
FORGEJO_PASSWORD = os.getenv("FORGEJO_PASSWORD", "")


def _client() -> httpx.Client:
    headers = {}
    auth = None
    if FORGEJO_TOKEN:
        headers["Authorization"] = f"token {FORGEJO_TOKEN}"
    elif FORGEJO_USER:
        auth = (FORGEJO_USER, FORGEJO_PASSWORD)
    return httpx.Client(base_url=FORGEJO_URL + "/api/v1", headers=headers, auth=auth, timeout=30)


@mcp.tool()
def get_current_user() -> str:
    """Get current authenticated user info."""
    with _client() as c:
        r = c.get("/user")
        r.raise_for_status()
    return json.dumps(r.json(), indent=2)


@mcp.tool()
def search_repos(query: str = "", limit: int = 20, topic: bool = False) -> str:
    """Search repositories.

    Args:
        query: Search string (empty = list all accessible repos)
        limit: Max results (default 20)
        topic: Search in topics (default False)
    """
    with _client() as c:
        r = c.get("/repos/search", params={"q": query, "limit": limit, "topic": topic})
        r.raise_for_status()
        data = r.json()
    repos = [
        {
            "full_name": repo["full_name"],
            "description": repo.get("description", ""),
            "stars": repo.get("stars_count", 0),
            "open_issues": repo.get("open_issues_count", 0),
            "default_branch": repo.get("default_branch", ""),
            "updated": repo.get("updated", ""),
            "clone_url": repo.get("clone_url", ""),
        }
        for repo in data.get("data", [])
    ]
    return json.dumps({"total": data.get("ok", len(repos)), "repos": repos}, indent=2)


@mcp.tool()
def get_repo(owner: str, repo: str) -> str:
    """Get repository details.

    Args:
        owner: Repository owner (user or org)
        repo: Repository name
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}")
        r.raise_for_status()
        data = r.json()
    return json.dumps({
        "full_name": data["full_name"],
        "description": data.get("description", ""),
        "default_branch": data.get("default_branch", ""),
        "stars": data.get("stars_count", 0),
        "forks": data.get("forks_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "topics": data.get("topics", []),
        "clone_url": data.get("clone_url", ""),
        "updated": data.get("updated", ""),
    }, indent=2)


@mcp.tool()
def list_issues(owner: str, repo: str, state: str = "open", issue_type: str = "issues", limit: int = 20) -> str:
    """List issues or pull requests for a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        state: "open", "closed", or "all" (default: open)
        issue_type: "issues" or "pulls" (default: issues)
        limit: Max results (default 20)
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/issues", params={"state": state, "type": issue_type, "limit": limit})
        r.raise_for_status()
        issues = r.json()
    return json.dumps([{
        "number": i["number"],
        "title": i["title"],
        "state": i["state"],
        "user": i["user"]["login"],
        "labels": [lb["name"] for lb in i.get("labels", [])],
        "comments": i.get("comments", 0),
        "created": i.get("created_at", ""),
        "updated": i.get("updated_at", ""),
        "url": i.get("html_url", ""),
    } for i in issues], indent=2)


@mcp.tool()
def get_issue(owner: str, repo: str, index: int) -> str:
    """Get a specific issue or pull request.

    Args:
        owner: Repository owner
        repo: Repository name
        index: Issue/PR number
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/issues/{index}")
        r.raise_for_status()
        i = r.json()
    return json.dumps({
        "number": i["number"],
        "title": i["title"],
        "body": i.get("body", ""),
        "state": i["state"],
        "user": i["user"]["login"],
        "labels": [lb["name"] for lb in i.get("labels", [])],
        "comments": i.get("comments", 0),
        "created": i.get("created_at", ""),
        "updated": i.get("updated_at", ""),
        "url": i.get("html_url", ""),
    }, indent=2)


@mcp.tool()
def create_issue(owner: str, repo: str, title: str, body: str = "", labels: list[str] | None = None) -> str:
    """Create a new issue.

    Args:
        owner: Repository owner
        repo: Repository name
        title: Issue title
        body: Issue body (markdown)
        labels: List of label names to apply
    """
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    with _client() as c:
        r = c.post(f"/repos/{owner}/{repo}/issues", json=payload)
        r.raise_for_status()
        i = r.json()
    return json.dumps({"number": i["number"], "url": i.get("html_url", ""), "state": i["state"]}, indent=2)


@mcp.tool()
def create_comment(owner: str, repo: str, index: int, body: str) -> str:
    """Add a comment to an issue or pull request.

    Args:
        owner: Repository owner
        repo: Repository name
        index: Issue/PR number
        body: Comment text (markdown)
    """
    with _client() as c:
        r = c.post(f"/repos/{owner}/{repo}/issues/{index}/comments", json={"body": body})
        r.raise_for_status()
        c_ = r.json()
    return json.dumps({"id": c_["id"], "created": c_.get("created_at", "")}, indent=2)


@mcp.tool()
def list_prs(owner: str, repo: str, state: str = "open", limit: int = 20) -> str:
    """List pull requests for a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        state: "open", "closed", or "all" (default: open)
        limit: Max results (default 20)
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/pulls", params={"state": state, "limit": limit})
        r.raise_for_status()
        prs = r.json()
    return json.dumps([{
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "user": pr["user"]["login"],
        "head": pr["head"]["label"],
        "base": pr["base"]["label"],
        "mergeable": pr.get("mergeable", None),
        "created": pr.get("created_at", ""),
        "updated": pr.get("updated_at", ""),
        "url": pr.get("html_url", ""),
    } for pr in prs], indent=2)


@mcp.tool()
def list_branches(owner: str, repo: str) -> str:
    """List branches for a repository.

    Args:
        owner: Repository owner
        repo: Repository name
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/branches")
        r.raise_for_status()
        branches = r.json()
    return json.dumps([{
        "name": b["name"],
        "protected": b.get("protected", False),
        "commit_sha": b["commit"]["id"][:8] if b.get("commit") else "",
        "commit_date": b["commit"].get("created", "") if b.get("commit") else "",
    } for b in branches], indent=2)


@mcp.tool()
def list_releases(owner: str, repo: str, limit: int = 10) -> str:
    """List releases for a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        limit: Max results (default 10)
    """
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/releases", params={"limit": limit})
        r.raise_for_status()
        releases = r.json()
    return json.dumps([{
        "tag": rel["tag_name"],
        "name": rel["name"],
        "draft": rel.get("draft", False),
        "prerelease": rel.get("prerelease", False),
        "published": rel.get("published_at", ""),
        "url": rel.get("html_url", ""),
    } for rel in releases], indent=2)


@mcp.tool()
def get_file_content(owner: str, repo: str, path: str, ref: str = "") -> str:
    """Get file content from a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        path: File path relative to repo root
        ref: Branch/tag/commit (default: default branch)
    """
    params = {}
    if ref:
        params["ref"] = ref
    with _client() as c:
        r = c.get(f"/repos/{owner}/{repo}/raw/{path}", params=params)
        r.raise_for_status()
    return json.dumps({"path": path, "ref": ref or "default", "content": r.text}, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
