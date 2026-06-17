"""MCP Server for git-write — propose code changes to any managed repo via
branch + commit + push + Pull Request (multi-repo, driven by GIT_REPOS).

This is the agent's self-improvement / contribution surface. Workflow:
    create_branch → (edit files with Write/Edit under the returned path)
    → commit_changes → push → open_pr  → a human reviews & merges.

Guardrails (code-side; GitHub branch protection is the real gate):
  - only 'claude/*' branches are created / committed / pushed;
  - protected branches (main/master/…) are never written or pushed;
  - PRs are opened for humans to merge, never merged here (Developer, not Maintainer).

This module is intentionally thin: it only wires MCP tools to the focused modules
`repos`, `branches`, `commits`, `pulls`.

Requires env vars:
  GITHUB_TOKEN   (push + pull_requests:write)
  GIT_REPOS      (JSON map of managed repos)
Optional: JARVIS_GIT_BRANCH_PREFIX, JARVIS_GIT_PROTECTED, JARVIS_GIT_NAME, JARVIS_GIT_EMAIL
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

import branches
import commits
import pulls
import repos

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("git-write")


def _j(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def list_writable_repos() -> str:
    """List the repos the agent can propose changes to (from GIT_REPOS), with
    their default/configured branch and GitHub slug."""
    out = []
    for name, info in repos.REPOS.items():
        slug = repos.github_slug(info["url"])
        out.append({
            "name": name,
            "url": info["url"],
            "configured_branch": info["branch"] or None,
            "github": "/".join(slug) if slug else None,
        })
    return _j({"repos": out, "branch_prefix": repos.ALLOWED_PREFIX,
               "protected": sorted(repos.PROTECTED_BRANCHES)})


@mcp.tool()
def create_branch(repo: str, branch: str, base: str = "") -> str:
    """Create (or reset) a 'claude/*' branch from origin/<base> in `repo`.

    Returns the working `path` to edit files under before committing. `base`
    defaults to the repo's default branch. Refuses non-'claude/*' or protected
    branch names.
    """
    return _j(branches.create_branch(repo, branch, base))


@mcp.tool()
def commit_changes(repo: str, message: str) -> str:
    """Stage all changes and commit them on the current claude/* branch of `repo`.
    Refuses to commit on a protected/non-prefixed branch or when nothing changed."""
    return _j(commits.commit_changes(repo, message))


@mcp.tool()
def push(repo: str, branch: str = "") -> str:
    """Push a claude/* branch to origin (default: current branch). Never pushes a
    protected branch."""
    return _j(commits.push(repo, branch))


@mcp.tool()
def open_pr(repo: str, title: str, body: str = "", base: str = "", head: str = "") -> str:
    """Open a Pull Request from a claude/* head branch into base (default: repo
    default branch), for a human to review and merge. Use the body to cover
    Context / Changes / Tests / Risks. Never merges."""
    return _j(pulls.open_pr(repo, title, body, base, head))


@mcp.tool()
def pr_status(repo: str, number: int) -> str:
    """Get the state of a Pull Request (open/closed/merged/mergeable)."""
    return _j(pulls.pr_status(repo, number))


if __name__ == "__main__":
    mcp.run()
