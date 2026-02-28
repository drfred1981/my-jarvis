"""MCP Server for Kubernetes cluster operations.

Provides tools to inspect and analyze a Kubernetes cluster:
- List and describe resources (pods, deployments, services, etc.)
- Read pod logs
- Get cluster health status
- Analyze resource usage
"""

import json
import logging

from mcp.server.fastmcp import FastMCP
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

mcp = FastMCP("kubernetes")


def get_k8s_clients():
    """Initialize Kubernetes clients (in-cluster or kubeconfig)."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.AppsV1Api(), client.NetworkingV1Api()


core_v1, apps_v1, networking_v1 = get_k8s_clients()


@mcp.tool()
def list_namespaces() -> str:
    """List all namespaces in the cluster."""
    namespaces = core_v1.list_namespace()
    return json.dumps([ns.metadata.name for ns in namespaces.items], indent=2)


@mcp.tool()
def list_pods(namespace: str = "default", label_selector: str = "") -> str:
    """List pods in a namespace, optionally filtered by label selector.

    Args:
        namespace: Kubernetes namespace (default: "default")
        label_selector: Optional label selector (e.g. "app=nginx")
    """
    kwargs = {"namespace": namespace}
    if label_selector:
        kwargs["label_selector"] = label_selector
    pods = core_v1.list_namespaced_pod(**kwargs)
    result = []
    for pod in pods.items:
        containers = []
        for cs in (pod.status.container_statuses or []):
            containers.append({
                "name": cs.name,
                "ready": cs.ready,
                "restarts": cs.restart_count,
                "state": _container_state(cs.state),
            })
        result.append({
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "phase": pod.status.phase,
            "node": pod.spec.node_name,
            "containers": containers,
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_pod_logs(name: str, namespace: str = "default", container: str = "", tail_lines: int = 100) -> str:
    """Get logs from a pod.

    Args:
        name: Pod name
        namespace: Kubernetes namespace
        container: Container name (optional, required for multi-container pods)
        tail_lines: Number of lines from the end (default: 100)
    """
    kwargs = {"name": name, "namespace": namespace, "tail_lines": tail_lines}
    if container:
        kwargs["container"] = container
    try:
        return core_v1.read_namespaced_pod_log(**kwargs)
    except ApiException as e:
        return f"Error reading logs: {e.reason}"


@mcp.tool()
def describe_pod(name: str, namespace: str = "default") -> str:
    """Get detailed information about a pod.

    Args:
        name: Pod name
        namespace: Kubernetes namespace
    """
    try:
        pod = core_v1.read_namespaced_pod(name=name, namespace=namespace)
        return json.dumps({
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "labels": pod.metadata.labels,
            "annotations": pod.metadata.annotations,
            "phase": pod.status.phase,
            "node": pod.spec.node_name,
            "ip": pod.status.pod_ip,
            "conditions": [
                {"type": c.type, "status": c.status, "reason": c.reason}
                for c in (pod.status.conditions or [])
            ],
            "containers": [
                {
                    "name": c.name,
                    "image": c.image,
                    "ports": [{"port": p.container_port, "protocol": p.protocol} for p in (c.ports or [])],
                    "resources": {
                        "requests": dict(c.resources.requests) if c.resources and c.resources.requests else {},
                        "limits": dict(c.resources.limits) if c.resources and c.resources.limits else {},
                    },
                }
                for c in pod.spec.containers
            ],
            "events": _get_events(namespace, f"Pod/{name}"),
        }, indent=2, default=str)
    except ApiException as e:
        return f"Error: {e.reason}"


@mcp.tool()
def list_deployments(namespace: str = "default") -> str:
    """List deployments in a namespace.

    Args:
        namespace: Kubernetes namespace
    """
    deps = apps_v1.list_namespaced_deployment(namespace=namespace)
    result = []
    for d in deps.items:
        result.append({
            "name": d.metadata.name,
            "replicas": f"{d.status.ready_replicas or 0}/{d.spec.replicas}",
            "available": d.status.available_replicas or 0,
            "updated": d.status.updated_replicas or 0,
            "images": [c.image for c in d.spec.template.spec.containers],
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def list_services(namespace: str = "default") -> str:
    """List services in a namespace.

    Args:
        namespace: Kubernetes namespace
    """
    svcs = core_v1.list_namespaced_service(namespace=namespace)
    result = []
    for svc in svcs.items:
        result.append({
            "name": svc.metadata.name,
            "type": svc.spec.type,
            "cluster_ip": svc.spec.cluster_ip,
            "ports": [
                {"port": p.port, "target_port": str(p.target_port), "protocol": p.protocol}
                for p in (svc.spec.ports or [])
            ],
            "selector": svc.spec.selector,
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_nodes_status() -> str:
    """Get status of all cluster nodes with resource usage."""
    nodes = core_v1.list_node()
    result = []
    for node in nodes.items:
        conditions = {c.type: c.status for c in node.status.conditions}
        result.append({
            "name": node.metadata.name,
            "ready": conditions.get("Ready", "Unknown"),
            "roles": [
                k.replace("node-role.kubernetes.io/", "")
                for k in (node.metadata.labels or {})
                if k.startswith("node-role.kubernetes.io/")
            ],
            "capacity": {
                "cpu": node.status.capacity.get("cpu"),
                "memory": node.status.capacity.get("memory"),
                "pods": node.status.capacity.get("pods"),
            },
            "allocatable": {
                "cpu": node.status.allocatable.get("cpu"),
                "memory": node.status.allocatable.get("memory"),
            },
            "os": node.status.node_info.os_image,
            "kubelet_version": node.status.node_info.kubelet_version,
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_cluster_health() -> str:
    """Get an overview of cluster health: nodes, problem pods, resource pressure."""
    nodes = core_v1.list_node()
    all_pods = core_v1.list_pod_for_all_namespaces()

    problem_pods = []
    for pod in all_pods.items:
        if pod.status.phase not in ("Running", "Succeeded"):
            problem_pods.append({
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "reason": pod.status.reason,
            })

    # High restart pods
    high_restart_pods = []
    for pod in all_pods.items:
        for cs in (pod.status.container_statuses or []):
            if cs.restart_count > 5:
                high_restart_pods.append({
                    "pod": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "container": cs.name,
                    "restarts": cs.restart_count,
                })

    node_issues = []
    for node in nodes.items:
        for c in node.status.conditions:
            if c.type != "Ready" and c.status == "True":
                node_issues.append({
                    "node": node.metadata.name,
                    "condition": c.type,
                    "message": c.message,
                })

    return json.dumps({
        "total_nodes": len(nodes.items),
        "total_pods": len(all_pods.items),
        "problem_pods": problem_pods,
        "high_restart_pods": high_restart_pods,
        "node_issues": node_issues,
    }, indent=2, default=str)


def _container_state(state) -> str:
    if state.running:
        return "running"
    if state.waiting:
        return f"waiting: {state.waiting.reason}"
    if state.terminated:
        return f"terminated: {state.terminated.reason}"
    return "unknown"


def _get_events(namespace: str, involved_object: str) -> list[dict]:
    """Get recent events for a resource."""
    try:
        events = core_v1.list_namespaced_event(namespace=namespace)
        kind, name = involved_object.split("/", 1)
        return [
            {
                "type": e.type,
                "reason": e.reason,
                "message": e.message,
                "count": e.count,
                "last_seen": str(e.last_timestamp),
            }
            for e in events.items
            if e.involved_object.kind == kind and e.involved_object.name == name
        ][-10:]  # Last 10 events
    except Exception:
        return []


if __name__ == "__main__":
    mcp.run(transport="stdio")
