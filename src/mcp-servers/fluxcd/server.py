"""MCP Server for FluxCD GitOps operations.

Provides tools to interact with FluxCD:
- Query FluxCD resources in the cluster (Kustomizations, HelmReleases, GitRepositories)
- Check reconciliation status
- Analyze the FluxCD git repository structure
- Propose changes via git operations
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

FLUX_REPO_URL = os.getenv("FLUX_REPO_URL", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

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


@mcp.tool()
def browse_flux_repo(path: str = "") -> str:
    """Browse the FluxCD git repository structure.

    Clones the repo temporarily and lists files at the given path.

    Args:
        path: Path within the repository to list (empty for root)
    """
    if not FLUX_REPO_URL:
        return "Error: FLUX_REPO_URL not configured"

    repo_url = FLUX_REPO_URL
    if GITHUB_TOKEN and "github.com" in repo_url:
        repo_url = repo_url.replace("https://", f"https://{GITHUB_TOKEN}@")

    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, tmpdir],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return f"Error cloning repo: {result.stderr}"

        target = os.path.join(tmpdir, path)
        if os.path.isfile(target):
            with open(target) as f:
                return f.read()
        elif os.path.isdir(target):
            entries = []
            for entry in sorted(os.listdir(target)):
                full = os.path.join(target, entry)
                entries.append({
                    "name": entry,
                    "type": "dir" if os.path.isdir(full) else "file",
                })
            return json.dumps(entries, indent=2)
        else:
            return f"Path not found: {path}"


@mcp.tool()
def read_flux_file(file_path: str) -> str:
    """Read a file from the FluxCD git repository.

    Args:
        file_path: Path to the file within the repository
    """
    if not FLUX_REPO_URL:
        return "Error: FLUX_REPO_URL not configured"

    repo_url = FLUX_REPO_URL
    if GITHUB_TOKEN and "github.com" in repo_url:
        repo_url = repo_url.replace("https://", f"https://{GITHUB_TOKEN}@")

    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, tmpdir],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return f"Error cloning repo: {result.stderr}"

        target = os.path.join(tmpdir, file_path)
        if not os.path.isfile(target):
            return f"File not found: {file_path}"
        with open(target) as f:
            return f.read()


if __name__ == "__main__":
    mcp.run(transport="stdio")
