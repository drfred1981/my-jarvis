"""MCP Server for Sonatype Nexus OSS (artifact repository manager).

Provides tools to interact with Nexus via its REST API v1:
- List and browse repositories
- Search components and assets
- Get component details and download URLs
- Check server status

Requires env vars:
  NEXUS_URL=http://nexus.nexus.svc.cluster.local:8081
  NEXUS_USER=admin
  NEXUS_PASSWORD=<password>
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("nexus")

NEXUS_URL = os.getenv("NEXUS_URL", "").rstrip("/")
NEXUS_USER = os.getenv("NEXUS_USER", "admin")
NEXUS_PASSWORD = os.getenv("NEXUS_PASSWORD", "")


def _client() -> httpx.Client:
    auth = (NEXUS_USER, NEXUS_PASSWORD) if NEXUS_USER else None
    return httpx.Client(base_url=f"{NEXUS_URL}/service/rest/v1", auth=auth, timeout=30)


@mcp.tool()
def get_status() -> str:
    """Get Nexus server status and system information."""
    with _client() as c:
        resp = c.get("/status")
        status_ok = resp.status_code == 200
    with _client() as c:
        resp2 = c.get("/status/check")
        check = resp2.json() if resp2.status_code == 200 else {}
    return json.dumps({"available": status_ok, "checks": check}, indent=2)


@mcp.tool()
def list_repositories() -> str:
    """List all repositories with their type, format and status."""
    with _client() as c:
        resp = c.get("/repositories")
        resp.raise_for_status()
    repos = [
        {
            "name": r["name"],
            "format": r.get("format", ""),
            "type": r.get("type", ""),
            "url": r.get("url", ""),
            "online": r.get("online", True),
        }
        for r in resp.json()
    ]
    repos.sort(key=lambda r: (r["format"], r["type"], r["name"]))
    return json.dumps({"count": len(repos), "repositories": repos}, indent=2)


@mcp.tool()
def search_components(
    query: str = "",
    repository: str = "",
    group: str = "",
    name: str = "",
    version: str = "",
    format: str = "",
) -> str:
    """Search for components (artifacts) across repositories.

    Args:
        query: Keyword search (searches name/group)
        repository: Filter by repository name
        group: Filter by group ID (Maven: groupId)
        name: Filter by artifact name (Maven: artifactId)
        version: Filter by version
        format: Filter by format (maven2, docker, npm, pypi, raw, ...)
    """
    params = {}
    if query:
        params["q"] = query
    if repository:
        params["repository"] = repository
    if group:
        params["group"] = group
    if name:
        params["name"] = name
    if version:
        params["version"] = version
    if format:
        params["format"] = format

    with _client() as c:
        resp = c.get("/search/assets", params=params)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", [])
    results = [
        {
            "repository": i.get("repository", ""),
            "format": i.get("format", ""),
            "group": i.get("maven2", {}).get("groupId", i.get("npm", {}).get("scope", "")),
            "name": i.get("maven2", {}).get("artifactId", i.get("name", "")),
            "version": i.get("maven2", {}).get("version", i.get("version", "")),
            "path": i.get("path", ""),
            "download_url": i.get("downloadUrl", ""),
            "checksum_sha1": i.get("checksum", {}).get("sha1", ""),
            "last_modified": i.get("lastModified", ""),
        }
        for i in items[:50]
    ]
    return json.dumps({
        "count": len(results),
        "continuation_token": data.get("continuationToken"),
        "items": results,
    }, indent=2)


@mcp.tool()
def list_components(repository: str, continuation_token: str = "") -> str:
    """List all components in a repository (paginated).

    Args:
        repository: Repository name
        continuation_token: Token for next page (from previous call)
    """
    params = {"repository": repository}
    if continuation_token:
        params["continuationToken"] = continuation_token

    with _client() as c:
        resp = c.get("/components", params=params)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", [])
    components = [
        {
            "id": i.get("id", ""),
            "repository": i.get("repository", ""),
            "format": i.get("format", ""),
            "group": i.get("group", ""),
            "name": i.get("name", ""),
            "version": i.get("version", ""),
            "assets_count": len(i.get("assets", [])),
        }
        for i in items
    ]
    return json.dumps({
        "count": len(components),
        "continuation_token": data.get("continuationToken"),
        "components": components,
    }, indent=2)


@mcp.tool()
def get_component(component_id: str) -> str:
    """Get detailed information about a specific component including its assets.

    Args:
        component_id: Component ID (from list_components or search_components)
    """
    with _client() as c:
        resp = c.get(f"/components/{component_id}")
        resp.raise_for_status()
    c_ = resp.json()
    assets = [
        {
            "path": a.get("path", ""),
            "download_url": a.get("downloadUrl", ""),
            "content_type": a.get("contentType", ""),
            "size": a.get("fileSize", 0),
            "last_modified": a.get("lastModified", ""),
            "checksum_sha1": a.get("checksum", {}).get("sha1", ""),
            "checksum_md5": a.get("checksum", {}).get("md5", ""),
        }
        for a in c_.get("assets", [])
    ]
    return json.dumps({
        "id": c_.get("id", ""),
        "repository": c_.get("repository", ""),
        "format": c_.get("format", ""),
        "group": c_.get("group", ""),
        "name": c_.get("name", ""),
        "version": c_.get("version", ""),
        "assets": assets,
    }, indent=2)


@mcp.tool()
def get_repository_details(repository: str) -> str:
    """Get configuration details of a specific repository.

    Args:
        repository: Repository name
    """
    with _client() as c:
        resp = c.get(f"/repositories/{repository}")
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
