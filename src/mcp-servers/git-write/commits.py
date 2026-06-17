"""Stage + commit + push for git-write.

All operations refuse protected / non-prefixed branches: the agent can only ever
publish work on a ``claude/*`` branch, never directly on main.
"""

from __future__ import annotations

import logging

import repos

logger = logging.getLogger(__name__)


def _checked_repo(repo: str):
    """Return (name, repo_dir) or ({"error":...}, None)."""
    info = repos.resolve(repo)
    if not info:
        return {"error": f"unknown repo '{repo}'"}, None
    rdir = repos.repo_dir(info[0])
    if not (rdir / ".git").exists():
        return {"error": f"repo '{info[0]}' not cloned — call create_branch first"}, None
    return info[0], rdir


def commit_changes(repo: str, message: str) -> dict:
    """Stage all changes and commit on the current (claude/*) branch."""
    name, rdir = _checked_repo(repo)
    if rdir is None:
        return name  # the error dict

    branch = repos.current_branch(rdir)
    if not repos.is_writable_branch(branch):
        return {"error": f"refusing to commit on '{branch}'; "
                         f"work on a '{repos.ALLOWED_PREFIX}*' branch (create_branch)"}

    repos.run_git(rdir, "add", "-A", timeout=30)
    _, status, _ = repos.run_git(rdir, "status", "--porcelain", timeout=15)
    if not status:
        return {"error": "nothing to commit (working tree clean)"}

    rc, _, er = repos.run_git(
        rdir, "-c", f"user.name={repos.GIT_NAME}", "-c", f"user.email={repos.GIT_EMAIL}",
        "commit", "-m", message, timeout=30)
    if rc != 0:
        return {"error": f"commit failed: {er}"}

    _, sha, _ = repos.run_git(rdir, "rev-parse", "HEAD", timeout=10)
    files = [ln[3:] for ln in status.splitlines()]
    return {"ok": True, "repo": name, "branch": branch, "sha": sha[:10],
            "files": files, "message": message}


def push(repo: str, branch: str = "") -> dict:
    """Push a claude/* branch to origin (sets upstream)."""
    name, rdir = _checked_repo(repo)
    if rdir is None:
        return name

    branch = branch or repos.current_branch(rdir)
    if not repos.is_writable_branch(branch):
        return {"error": f"refusing to push '{branch}' "
                         f"(only '{repos.ALLOWED_PREFIX}*' branches, never protected)"}

    rc, _, er = repos.run_git(rdir, "push", "-u", "origin", branch, timeout=120)
    if rc != 0:
        return {"error": f"push failed: {er}"}
    return {"ok": True, "repo": name, "branch": branch, "pushed": True}
