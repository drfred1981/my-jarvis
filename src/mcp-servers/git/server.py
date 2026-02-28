"""MCP Server for multi-repository git operations.

Manages multiple git repositories independently:
- Browse, read, search files across repos
- View git history, branches, diffs
- Supports any git hosting (GitHub, GitLab, Gitea, etc.)

Repos are configured via GIT_REPOS env var:
  GIT_REPOS='{"my-jarvis":"https://github.com/user/my-jarvis.git","infra":"https://github.com/user/infra.git"}'
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("git")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Persistent clone cache to avoid re-cloning every call
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "jarvis-git-cache")


def _load_repos() -> dict[str, str]:
    """Load repos from GIT_REPOS env var."""
    repos = {}
    repos_json = os.getenv("GIT_REPOS", "")
    if repos_json:
        try:
            repos.update(json.loads(repos_json))
        except json.JSONDecodeError:
            logger.error("Invalid GIT_REPOS JSON: %s", repos_json)
    return repos


REPOS = _load_repos()


def _auth_url(url: str) -> str:
    """Inject auth token into git URL if applicable."""
    if GITHUB_TOKEN and "github.com" in url:
        return url.replace("https://", f"https://{GITHUB_TOKEN}@")
    return url


def _get_repo_dir(name: str) -> Path:
    """Get the local cache directory for a repo."""
    return Path(_CACHE_DIR) / name


def _ensure_cloned(name: str, url: str, branch: str = "") -> str | None:
    """Clone or update a repo in cache. Returns error string or None."""
    repo_dir = _get_repo_dir(name)
    auth_url = _auth_url(url)

    if repo_dir.exists() and (repo_dir / ".git").exists():
        # Pull latest
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "fetch", "--all", "--prune"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return f"fetch error: {result.stderr.strip()}"

        target_branch = branch or _get_default_branch(repo_dir)
        subprocess.run(
            ["git", "-C", str(repo_dir), "checkout", target_branch],
            capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=60,
        )
        return None
    else:
        # Fresh clone
        repo_dir.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone"]
        if branch:
            cmd.extend(["--branch", branch])
        cmd.extend([auth_url, str(repo_dir)])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return f"clone error: {result.stderr.strip()}"
        return None


def _get_default_branch(repo_dir: Path) -> str:
    """Get the default branch of a cloned repo."""
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return result.stdout.strip().replace("refs/remotes/origin/", "")
    return "main"


def _resolve_repo(name: str) -> tuple[str, str] | None:
    """Resolve a repo name to (name, url)."""
    if not name and len(REPOS) == 1:
        k = next(iter(REPOS))
        return k, REPOS[k]
    if name in REPOS:
        return name, REPOS[name]
    # Partial match
    matches = [(k, v) for k, v in REPOS.items() if name in k]
    if len(matches) == 1:
        return matches[0]
    return None


@mcp.tool()
def list_repos() -> str:
    """List all configured git repositories."""
    if not REPOS:
        return "No repositories configured. Set GIT_REPOS env var."
    return json.dumps([{"name": k, "url": v} for k, v in REPOS.items()], indent=2)


@mcp.tool()
def browse(repo: str = "", path: str = "", branch: str = "") -> str:
    """Browse a repository file tree.

    Args:
        repo: Repository name (use list_repos to see available). Auto-selected if only one.
        path: Path within the repo (empty for root)
        branch: Git branch (empty for default)
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        return _repo_not_found_error(repo)
    name, url = resolved

    err = _ensure_cloned(name, url, branch)
    if err:
        return f"Error accessing {name}: {err}"

    repo_dir = _get_repo_dir(name)
    target = repo_dir / path

    if target.is_file():
        return target.read_text(errors="replace")
    elif target.is_dir():
        entries = []
        for entry in sorted(target.iterdir()):
            if entry.name.startswith(".git"):
                continue
            entries.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
            })
        return json.dumps({"repo": name, "path": path or "/", "entries": entries}, indent=2)
    else:
        return f"Path not found in {name}: {path}"


@mcp.tool()
def read_file(file_path: str, repo: str = "", branch: str = "") -> str:
    """Read a file from a repository.

    Args:
        file_path: Path to the file within the repository
        repo: Repository name
        branch: Git branch (empty for default)
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        return _repo_not_found_error(repo)
    name, url = resolved

    err = _ensure_cloned(name, url, branch)
    if err:
        return f"Error accessing {name}: {err}"

    target = _get_repo_dir(name) / file_path
    if not target.is_file():
        return f"File not found in {name}: {file_path}"
    return target.read_text(errors="replace")


@mcp.tool()
def search_files(pattern: str, repo: str = "", path: str = "") -> str:
    """Search for content in a repository using grep.

    Args:
        pattern: Search pattern (regex)
        repo: Repository name
        path: Subdirectory to search in (empty for entire repo)
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        return _repo_not_found_error(repo)
    name, url = resolved

    err = _ensure_cloned(name, url)
    if err:
        return f"Error accessing {name}: {err}"

    search_dir = str(_get_repo_dir(name) / path) if path else str(_get_repo_dir(name))
    result = subprocess.run(
        ["grep", "-rn", "--include=*", "-I", pattern, search_dir],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode == 1:
        return f"No matches for '{pattern}' in {name}/{path}"

    # Strip the cache dir prefix from output
    cache_prefix = str(_get_repo_dir(name)) + "/"
    lines = result.stdout.replace(cache_prefix, "").strip()
    # Limit output
    output_lines = lines.split("\n")
    if len(output_lines) > 50:
        return "\n".join(output_lines[:50]) + f"\n... ({len(output_lines) - 50} more matches)"
    return lines


@mcp.tool()
def git_log(repo: str = "", count: int = 20, path: str = "") -> str:
    """Show git commit history.

    Args:
        repo: Repository name
        count: Number of commits to show (default: 20)
        path: File/directory path to filter history (empty for all)
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        return _repo_not_found_error(repo)
    name, url = resolved

    err = _ensure_cloned(name, url)
    if err:
        return f"Error accessing {name}: {err}"

    cmd = [
        "git", "-C", str(_get_repo_dir(name)),
        "log", f"-{count}", "--format=%H|%an|%ad|%s", "--date=short",
    ]
    if path:
        cmd.extend(["--", path])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0][:8],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
    return json.dumps({"repo": name, "commits": commits}, indent=2)


@mcp.tool()
def git_diff(repo: str = "", ref1: str = "HEAD~1", ref2: str = "HEAD", path: str = "") -> str:
    """Show diff between two references.

    Args:
        repo: Repository name
        ref1: First reference (default: HEAD~1)
        ref2: Second reference (default: HEAD)
        path: File/directory to diff (empty for all)
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        return _repo_not_found_error(repo)
    name, url = resolved

    err = _ensure_cloned(name, url)
    if err:
        return f"Error accessing {name}: {err}"

    cmd = ["git", "-C", str(_get_repo_dir(name)), "diff", ref1, ref2]
    if path:
        cmd.extend(["--", path])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    diff = result.stdout.strip()
    if not diff:
        return f"No differences between {ref1} and {ref2}"
    # Limit output
    lines = diff.split("\n")
    if len(lines) > 200:
        return "\n".join(lines[:200]) + f"\n... ({len(lines) - 200} more lines)"
    return diff


@mcp.tool()
def list_branches(repo: str = "") -> str:
    """List branches of a repository.

    Args:
        repo: Repository name
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        return _repo_not_found_error(repo)
    name, url = resolved

    err = _ensure_cloned(name, url)
    if err:
        return f"Error accessing {name}: {err}"

    result = subprocess.run(
        ["git", "-C", str(_get_repo_dir(name)), "branch", "-a", "--format=%(refname:short)"],
        capture_output=True, text=True, timeout=10,
    )
    branches = [b.strip() for b in result.stdout.strip().split("\n") if b.strip()]
    return json.dumps({"repo": name, "branches": branches}, indent=2)


def _repo_not_found_error(name: str) -> str:
    if not REPOS:
        return "No repositories configured. Set GIT_REPOS env var."
    return (
        f"Repository '{name}' not found. Available repos:\n"
        + json.dumps(list(REPOS.keys()), indent=2)
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
