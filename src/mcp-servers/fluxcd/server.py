"""MCP Server for FluxCD GitOps operations.

Provides tools to interact with FluxCD:
- Query FluxCD resources in the cluster (Kustomizations, HelmReleases, GitRepositories)
- Check reconciliation status
- Browse and read files from multiple git repositories
- Discover repos from FluxCD GitRepository CRDs in the cluster

Supports multiple repositories:
- Configured via FLUX_REPOS env var (JSON: {"name": "url", ...})
- Auto-discovered from FluxCD GitRepository resources in the cluster
"""

import json
import logging
import os
import subprocess
import tempfile

from mcp.server.fastmcp import FastMCP
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

mcp = FastMCP("fluxcd")

# Multiple repos: JSON dict {"alias": "https://github.com/...", ...}
# Also supports legacy single FLUX_REPO_URL
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

def _load_configured_repos() -> dict[str, str]:
    """Load repos from env config."""
    repos = {}

    # New multi-repo format: FLUX_REPOS='{"infra":"https://...","apps":"https://..."}'
    repos_json = os.getenv("FLUX_REPOS", "")
    if repos_json:
        try:
            repos.update(json.loads(repos_json))
        except json.JSONDecodeError:
            logger.error("Invalid FLUX_REPOS JSON: %s", repos_json)

    # Legacy single repo support
    legacy_url = os.getenv("FLUX_REPO_URL", "")
    if legacy_url and "default" not in repos:
        repos["default"] = legacy_url

    return repos


CONFIGURED_REPOS = _load_configured_repos()

# Initialize K8s client
try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

custom_api = client.CustomObjectsApi()

# FluxCD CRD groups
FLUX_GROUP = "source.toolkit.fluxcd.io"
KUSTOMIZE_GROUP = "kustomize.toolkit.fluxcd.io"
HELM_GROUP = "helm.toolkit.fluxcd.io"


def _discover_repos_from_cluster() -> dict[str, str]:
    """Discover git repositories from FluxCD GitRepository CRDs."""
    repos = {}
    try:
        items = custom_api.list_cluster_custom_object(
            FLUX_GROUP, "v1", "gitrepositories"
        )
        for item in items.get("items", []):
            name = item["metadata"]["name"]
            ns = item["metadata"]["namespace"]
            url = item["spec"].get("url", "")
            if url:
                repos[f"{ns}/{name}"] = url
    except Exception as e:
        logger.debug("Could not discover repos from cluster: %s", e)
    return repos


def _get_all_repos() -> dict[str, str]:
    """Get all known repos: configured + discovered from cluster."""
    repos = dict(CONFIGURED_REPOS)
    repos.update(_discover_repos_from_cluster())
    return repos


def _auth_url(url: str) -> str:
    """Inject auth token into a git URL if applicable."""
    if GITHUB_TOKEN and "github.com" in url:
        return url.replace("https://", f"https://{GITHUB_TOKEN}@")
    return url


def _clone_repo(url: str, tmpdir: str, branch: str = "") -> str | None:
    """Clone a repo to tmpdir. Returns error string or None on success."""
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([_auth_url(url), tmpdir])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return result.stderr.strip()
    return None


def _resolve_repo(repo: str) -> tuple[str, str] | None:
    """Resolve a repo alias or name to (name, url). Returns None if not found."""
    all_repos = _get_all_repos()

    if not repo:
        # If only one repo, use it
        if len(all_repos) == 1:
            name = next(iter(all_repos))
            return name, all_repos[name]
        return None

    # Exact match
    if repo in all_repos:
        return repo, all_repos[repo]

    # Partial match
    matches = [(k, v) for k, v in all_repos.items() if repo in k]
    if len(matches) == 1:
        return matches[0]

    return None


# --- Cluster resource tools ---

@mcp.tool()
def list_git_repositories(namespace: str = "") -> str:
    """List FluxCD GitRepository sources.

    Args:
        namespace: Filter by namespace (empty for all namespaces)
    """
    try:
        if namespace:
            items = custom_api.list_namespaced_custom_object(
                FLUX_GROUP, "v1", namespace, "gitrepositories"
            )
        else:
            items = custom_api.list_cluster_custom_object(
                FLUX_GROUP, "v1", "gitrepositories"
            )
        result = []
        for item in items.get("items", []):
            status = item.get("status", {})
            conditions = status.get("conditions", [])
            ready = next((c for c in conditions if c["type"] == "Ready"), {})
            result.append({
                "name": item["metadata"]["name"],
                "namespace": item["metadata"]["namespace"],
                "url": item["spec"].get("url", ""),
                "branch": item["spec"].get("ref", {}).get("branch", ""),
                "ready": ready.get("status", "Unknown"),
                "message": ready.get("message", ""),
            })
        return json.dumps(result, indent=2)
    except ApiException as e:
        return f"Error: {e.reason}"


@mcp.tool()
def list_kustomizations(namespace: str = "") -> str:
    """List FluxCD Kustomizations.

    Args:
        namespace: Filter by namespace (empty for all namespaces)
    """
    try:
        if namespace:
            items = custom_api.list_namespaced_custom_object(
                KUSTOMIZE_GROUP, "v1", namespace, "kustomizations"
            )
        else:
            items = custom_api.list_cluster_custom_object(
                KUSTOMIZE_GROUP, "v1", "kustomizations"
            )
        result = []
        for item in items.get("items", []):
            status = item.get("status", {})
            conditions = status.get("conditions", [])
            ready = next((c for c in conditions if c["type"] == "Ready"), {})
            result.append({
                "name": item["metadata"]["name"],
                "namespace": item["metadata"]["namespace"],
                "path": item["spec"].get("path", ""),
                "source": item["spec"].get("sourceRef", {}).get("name", ""),
                "ready": ready.get("status", "Unknown"),
                "message": ready.get("message", ""),
                "last_applied_revision": status.get("lastAppliedRevision", ""),
            })
        return json.dumps(result, indent=2)
    except ApiException as e:
        return f"Error: {e.reason}"


@mcp.tool()
def list_helm_releases(namespace: str = "") -> str:
    """List FluxCD HelmReleases.

    Args:
        namespace: Filter by namespace (empty for all namespaces)
    """
    try:
        if namespace:
            items = custom_api.list_namespaced_custom_object(
                HELM_GROUP, "v2", namespace, "helmreleases"
            )
        else:
            items = custom_api.list_cluster_custom_object(
                HELM_GROUP, "v2", "helmreleases"
            )
        result = []
        for item in items.get("items", []):
            status = item.get("status", {})
            conditions = status.get("conditions", [])
            ready = next((c for c in conditions if c["type"] == "Ready"), {})
            spec = item.get("spec", {})
            chart = spec.get("chart", {}).get("spec", {})
            result.append({
                "name": item["metadata"]["name"],
                "namespace": item["metadata"]["namespace"],
                "chart": chart.get("chart", ""),
                "version": chart.get("version", ""),
                "source": chart.get("sourceRef", {}).get("name", ""),
                "ready": ready.get("status", "Unknown"),
                "message": ready.get("message", ""),
                "installed_version": status.get("lastAttemptedRevision", ""),
            })
        return json.dumps(result, indent=2)
    except ApiException as e:
        return f"Error: {e.reason}"


@mcp.tool()
def get_reconciliation_status() -> str:
    """Get an overview of all FluxCD reconciliation statuses."""
    report = {"git_repositories": [], "kustomizations": [], "helm_releases": []}

    try:
        grs = custom_api.list_cluster_custom_object(FLUX_GROUP, "v1", "gitrepositories")
        for item in grs.get("items", []):
            conditions = item.get("status", {}).get("conditions", [])
            ready = next((c for c in conditions if c["type"] == "Ready"), {})
            if ready.get("status") != "True":
                report["git_repositories"].append({
                    "name": f"{item['metadata']['namespace']}/{item['metadata']['name']}",
                    "status": ready.get("status"),
                    "message": ready.get("message", ""),
                })
    except ApiException:
        report["git_repositories"] = "error fetching"

    try:
        ks = custom_api.list_cluster_custom_object(KUSTOMIZE_GROUP, "v1", "kustomizations")
        for item in ks.get("items", []):
            conditions = item.get("status", {}).get("conditions", [])
            ready = next((c for c in conditions if c["type"] == "Ready"), {})
            if ready.get("status") != "True":
                report["kustomizations"].append({
                    "name": f"{item['metadata']['namespace']}/{item['metadata']['name']}",
                    "status": ready.get("status"),
                    "message": ready.get("message", ""),
                })
    except ApiException:
        report["kustomizations"] = "error fetching"

    try:
        hrs = custom_api.list_cluster_custom_object(HELM_GROUP, "v2", "helmreleases")
        for item in hrs.get("items", []):
            conditions = item.get("status", {}).get("conditions", [])
            ready = next((c for c in conditions if c["type"] == "Ready"), {})
            if ready.get("status") != "True":
                report["helm_releases"].append({
                    "name": f"{item['metadata']['namespace']}/{item['metadata']['name']}",
                    "status": ready.get("status"),
                    "message": ready.get("message", ""),
                })
    except ApiException:
        report["helm_releases"] = "error fetching"

    return json.dumps(report, indent=2)


# --- Git repository browsing tools (multi-repo) ---

@mcp.tool()
def list_repos() -> str:
    """List all known git repositories (configured + discovered from cluster)."""
    all_repos = _get_all_repos()
    result = [{"name": k, "url": v} for k, v in all_repos.items()]
    return json.dumps(result, indent=2)


@mcp.tool()
def browse_repo(repo: str = "", path: str = "", branch: str = "") -> str:
    """Browse a git repository structure. Lists files/directories at the given path.

    Args:
        repo: Repository name or alias (use list_repos to see available repos).
              If only one repo is configured, it is used by default.
        path: Path within the repository to list (empty for root)
        branch: Git branch to browse (empty for default branch)
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        all_repos = _get_all_repos()
        if not all_repos:
            return "Error: no git repositories configured. Set FLUX_REPOS or FLUX_REPO_URL."
        return (
            f"Error: repo '{repo}' not found. Available repos:\n"
            + json.dumps(list(all_repos.keys()), indent=2)
        )

    repo_name, repo_url = resolved

    with tempfile.TemporaryDirectory() as tmpdir:
        err = _clone_repo(repo_url, tmpdir, branch)
        if err:
            return f"Error cloning {repo_name}: {err}"

        target = os.path.join(tmpdir, path)
        if os.path.isfile(target):
            with open(target) as f:
                return f.read()
        elif os.path.isdir(target):
            entries = []
            for entry in sorted(os.listdir(target)):
                if entry.startswith(".git"):
                    continue
                full = os.path.join(target, entry)
                entries.append({
                    "name": entry,
                    "type": "dir" if os.path.isdir(full) else "file",
                })
            return json.dumps({"repo": repo_name, "path": path or "/", "entries": entries}, indent=2)
        else:
            return f"Path not found: {path}"


@mcp.tool()
def read_repo_file(file_path: str, repo: str = "", branch: str = "") -> str:
    """Read a file from a git repository.

    Args:
        file_path: Path to the file within the repository
        repo: Repository name or alias (use list_repos to see available repos).
              If only one repo is configured, it is used by default.
        branch: Git branch (empty for default branch)
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        all_repos = _get_all_repos()
        if not all_repos:
            return "Error: no git repositories configured."
        return (
            f"Error: repo '{repo}' not found. Available repos:\n"
            + json.dumps(list(all_repos.keys()), indent=2)
        )

    repo_name, repo_url = resolved

    with tempfile.TemporaryDirectory() as tmpdir:
        err = _clone_repo(repo_url, tmpdir, branch)
        if err:
            return f"Error cloning {repo_name}: {err}"

        target = os.path.join(tmpdir, file_path)
        if not os.path.isfile(target):
            return f"File not found in {repo_name}: {file_path}"
        with open(target) as f:
            return f.read()


if __name__ == "__main__":
    mcp.run(transport="stdio")
