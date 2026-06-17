"""Repo plumbing for the git-write MCP.

GIT_REPOS resolution, authenticated URLs, the clone cache, git subprocess
helpers and GitHub slug parsing — shared by `branches`, `commits`, `pulls`.

Imported flat (``import repos``): the MCP server runs as a script, so its own
directory is first on sys.path and these modules resolve locally.

Env: GITHUB_TOKEN (push + PR), GIT_REPOS, optional JARVIS_GIT_* overrides.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

_PROJECT_DIR = os.environ.get("JARVIS_PROJECT_DIR", "/home/jarvis")
# Shared with the read-only git MCP and the dispatcher pre-clone.
CACHE_DIR = os.path.join(_PROJECT_DIR, "git-cache")

# Branch policy (code-side guardrails; GitHub branch protection is the real gate).
ALLOWED_PREFIX = os.getenv("JARVIS_GIT_BRANCH_PREFIX", "claude/")
PROTECTED_BRANCHES = {
    b.strip().lower()
    for b in os.getenv("JARVIS_GIT_PROTECTED", "main,master,develop,production").split(",")
    if b.strip()
}

GIT_NAME = os.getenv("JARVIS_GIT_NAME", "Jarvis")
GIT_EMAIL = os.getenv("JARVIS_GIT_EMAIL", "jarvis@localhost")


def load_repos() -> dict[str, dict]:
    """Parse GIT_REPOS (string or {url,branch} per repo)."""
    repos: dict[str, dict] = {}
    raw_json = os.getenv("GIT_REPOS", "")
    if not raw_json:
        return repos
    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error("Invalid GIT_REPOS JSON: %s", e)
        return repos
    for name, value in raw.items():
        if isinstance(value, str):
            repos[name] = {"url": value, "branch": ""}
        elif isinstance(value, dict):
            repos[name] = {"url": value["url"], "branch": value.get("branch", "")}
        else:
            logger.warning("Skipping repo %s: unexpected type %s", name, type(value))
    return repos


REPOS = load_repos()


def auth_url(url: str) -> str:
    if GITHUB_TOKEN and "github.com" in url:
        return url.replace("https://", f"https://{GITHUB_TOKEN}@")
    return url


def repo_dir(name: str) -> Path:
    return Path(CACHE_DIR) / name


def resolve(name: str):
    """Return (name, url, configured_branch) or None.

    If `name` is empty and exactly one repo is configured, it is used.
    """
    if not name and len(REPOS) == 1:
        name = next(iter(REPOS))
    info = REPOS.get(name)
    if not info:
        return None
    return name, info["url"], info["branch"]


def run_git(rdir, *args, timeout: int = 60):
    """Run `git -C <rdir> <args>`; return (returncode, stdout, stderr)."""
    res = subprocess.run(["git", "-C", str(rdir), *args],
                         capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def ensure_cloned(name: str):
    """Clone or fetch the repo into cache. Returns (repo_dir, None) or (None, error)."""
    info = resolve(name)
    if not info:
        known = ", ".join(REPOS) or "none"
        return None, f"unknown repo '{name}' (known: {known})"
    rname, url, _ = info
    rdir = repo_dir(rname)
    au = auth_url(url)
    if (rdir / ".git").exists():
        run_git(rdir, "remote", "set-url", "origin", au, timeout=15)
        rc, _, err = run_git(rdir, "fetch", "--all", "--prune", timeout=120)
        if rc != 0:
            return None, f"fetch error: {err}"
        return rdir, None
    if rdir.exists():
        shutil.rmtree(rdir, ignore_errors=True)
    rdir.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(["git", "clone", au, str(rdir)],
                         capture_output=True, text=True, timeout=180)
    if res.returncode != 0:
        return None, f"clone error: {res.stderr.strip()}"
    return rdir, None


def default_branch(rdir) -> str:
    rc, out, _ = run_git(rdir, "symbolic-ref", "refs/remotes/origin/HEAD", timeout=10)
    if rc == 0 and out:
        return out.replace("refs/remotes/origin/", "")
    return "main"


def current_branch(rdir) -> str:
    rc, out, _ = run_git(rdir, "rev-parse", "--abbrev-ref", "HEAD", timeout=10)
    return out if rc == 0 else ""


def is_protected(branch: str) -> bool:
    return branch.strip().lower() in PROTECTED_BRANCHES


def is_writable_branch(branch: str) -> bool:
    """A branch we are allowed to create/commit/push to."""
    return branch.startswith(ALLOWED_PREFIX) and not is_protected(branch)


def github_slug(url: str):
    """Parse (owner, repo) from a GitHub URL, or None."""
    m = re.search(r"github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$", url)
    return (m.group(1), m.group(2)) if m else None
