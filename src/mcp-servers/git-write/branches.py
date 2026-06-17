"""Branch lifecycle for git-write + the core guardrail.

Only ``ALLOWED_PREFIX`` (default ``claude/``) branches may be created; protected
branches are never written. A new branch is always cut fresh from ``origin/<base>``.
"""

from __future__ import annotations

import logging

import repos

logger = logging.getLogger(__name__)


def create_branch(repo: str, branch: str, base: str = "") -> dict:
    """Clone/fetch the repo, then create (or reset) `branch` from origin/<base>.

    Returns the working `path` so the agent can edit files there before
    committing.
    """
    if not branch.startswith(repos.ALLOWED_PREFIX):
        return {"error": f"branch must start with '{repos.ALLOWED_PREFIX}' (got '{branch}')"}
    if repos.is_protected(branch):
        return {"error": f"'{branch}' is a protected branch"}

    rdir, err = repos.ensure_cloned(repo)
    if err:
        return {"error": err}

    name = repos.resolve(repo)[0]
    base = base or repos.default_branch(rdir)

    rc, _, er = repos.run_git(rdir, "checkout", base, timeout=30)
    if rc != 0:
        return {"error": f"checkout {base}: {er}"}
    repos.run_git(rdir, "reset", "--hard", f"origin/{base}", timeout=30)

    rc, _, er = repos.run_git(rdir, "checkout", "-B", branch, f"origin/{base}", timeout=30)
    if rc != 0:
        return {"error": f"create branch '{branch}': {er}"}

    return {
        "ok": True,
        "repo": name,
        "branch": branch,
        "base": base,
        "path": str(rdir),
        "hint": "Edit files under `path` with Write/Edit, then commit_changes → push → open_pr.",
    }
