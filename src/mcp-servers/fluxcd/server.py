"""MCP Server for FluxCD GitOps operations.

Provides tools to query FluxCD resources in the cluster:
- GitRepositories, Kustomizations, HelmReleases
- Reconciliation status overview

For browsing git repository content, use the git MCP server instead.
"""

import json
import logging

from mcp.server.fastmcp import FastMCP
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

mcp = FastMCP("fluxcd")

_custom_api = None
_k8s_init_error = None


def _api() -> client.CustomObjectsApi:
    """Lazy-init Kubernetes client."""
    global _custom_api, _k8s_init_error
    if _custom_api is not None:
        return _custom_api
    if _k8s_init_error:
        raise RuntimeError(_k8s_init_error)
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        _custom_api = client.CustomObjectsApi()
        return _custom_api
    except Exception as e:
        _k8s_init_error = f"Kubernetes not available: {e}"
        raise RuntimeError(_k8s_init_error)

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
            items = _api().list_namespaced_custom_object(
                FLUX_GROUP, "v1", namespace, "gitrepositories"
            )
        else:
            items = _api().list_cluster_custom_object(
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
            items = _api().list_namespaced_custom_object(
                KUSTOMIZE_GROUP, "v1", namespace, "kustomizations"
            )
        else:
            items = _api().list_cluster_custom_object(
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
            items = _api().list_namespaced_custom_object(
                HELM_GROUP, "v2", namespace, "helmreleases"
            )
        else:
            items = _api().list_cluster_custom_object(
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
    """Get an overview of all FluxCD reconciliation statuses.

    Returns only resources that are NOT ready (problems).
    """
    report = {"git_repositories": [], "kustomizations": [], "helm_releases": []}

    try:
        grs = _api().list_cluster_custom_object(FLUX_GROUP, "v1", "gitrepositories")
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
        ks = _api().list_cluster_custom_object(KUSTOMIZE_GROUP, "v1", "kustomizations")
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
        hrs = _api().list_cluster_custom_object(HELM_GROUP, "v2", "helmreleases")
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
