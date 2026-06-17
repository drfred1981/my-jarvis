"""GitHub Pull Request API for git-write — open and inspect PRs. Never merges.

The agent has the *Developer* role: it proposes via PR and a human reviews/merges.
Branch protection on the GitHub side is the real guardrail; here we only ensure a
PR's head is a ``claude/*`` branch and never call the merge endpoint.
"""

from __future__ import annotations

import logging

import httpx
import repos

logger = logging.getLogger(__name__)

API = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {repos.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def open_pr(repo: str, title: str, body: str = "", base: str = "", head: str = "") -> dict:
    """Open a PR from a claude/* head branch into base (default: repo default)."""
    info = repos.resolve(repo)
    if not info:
        return {"error": f"unknown repo '{repo}'"}
    name, url, _ = info
    slug = repos.github_slug(url)
    if not slug:
        return {"error": f"not a GitHub repo: {url}"}

    rdir = repos.repo_dir(name)
    head = head or repos.current_branch(rdir)
    base = base or repos.default_branch(rdir)
    if not head.startswith(repos.ALLOWED_PREFIX):
        return {"error": f"PR head '{head}' must start with '{repos.ALLOWED_PREFIX}'"}
    if head == base:
        return {"error": "head and base are the same branch"}

    owner, rname = slug
    try:
        resp = httpx.post(f"{API}/repos/{owner}/{rname}/pulls", headers=_headers(),
                          json={"title": title, "body": body, "head": head, "base": base},
                          timeout=30)
    except httpx.HTTPError as e:
        return {"error": f"GitHub API error: {e}"}
    if resp.status_code >= 300:
        return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}

    pr = resp.json()
    return {"ok": True, "repo": name, "number": pr.get("number"),
            "url": pr.get("html_url"), "head": head, "base": base}


def pr_status(repo: str, number: int) -> dict:
    """Get the state of a PR (open/closed/merged/mergeable)."""
    info = repos.resolve(repo)
    if not info:
        return {"error": f"unknown repo '{repo}'"}
    slug = repos.github_slug(info[1])
    if not slug:
        return {"error": "not a GitHub repo"}

    owner, rname = slug
    try:
        resp = httpx.get(f"{API}/repos/{owner}/{rname}/pulls/{number}",
                         headers=_headers(), timeout=30)
    except httpx.HTTPError as e:
        return {"error": f"GitHub API error: {e}"}
    if resp.status_code >= 300:
        return {"error": f"GitHub API {resp.status_code}: {resp.text[:200]}"}

    pr = resp.json()
    return {"ok": True, "number": pr.get("number"), "state": pr.get("state"),
            "merged": pr.get("merged"), "mergeable": pr.get("mergeable"),
            "title": pr.get("title"), "url": pr.get("html_url")}
