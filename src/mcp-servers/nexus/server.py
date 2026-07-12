"""MCP Server for Nexus Repository Manager 3.x.

Provides tools to interact with Nexus via its REST API:
- List and browse repositories
- Search for components/artifacts (by group, artifact, version)
- List assets in a repository
- Get component/asset details

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
NEXUS_USER = os.getenv("NEXUS_USER", "")
NEXUS_PASSWORD = os.getenv("NEXUS_PASSWORD", "")


def _client() -> httpx.Client:
    auth = (NEXUS_USER, NEXUS_PASSWORD) if NEXUS_USER else None
    return httpx.Client(base_url=NEXUS_URL + "/service/rest/v1", auth=auth, timeout=30)


@mcp.tool()
def list_repositories() -> str:
    """List all Nexus repositories with their type and format."""
    with _client() as c:
        r = c.get("/repositories")
        r.raise_for_status()
        repos = r.json()
    return json.dumps([{
        "name": repo["name"],
        "format": repo.get("format", ""),
        "type": repo.get("type", ""),
        "url": repo.get("url", ""),
    } for repo in repos], indent=2)


@mcp.tool()
def search_components(
    repository: str = "",
    group: str = "",
    name: str = "",
    version: str = "",
    format: str = "",
    limit: int = 20,
) -> str:
    """Search for components (artifacts) in Nexus.

    Args:
        repository: Filter by repository name (optional)
        group: Maven groupId or npm scope (optional)
        name: Artifact name / artifactId (optional)
        version: Version string, supports wildcards (optional)
        format: Format filter: maven2, npm, docker, raw, pypi, etc. (optional)
        limit: Max results (default 20, max 50)
    """
    params: dict = {}
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

    components = []
    continuation_token = None

    with _client() as c:
        while len(components) < limit:
            if continuation_token:
                params["continuationToken"] = continuation_token
            r = c.get("/search/assets", params=params)
            r.raise_for_status()
            data = r.json()
            items = data.get("items", [])
            components.extend(items)
            continuation_token = data.get("continuationToken")
            if not continuation_token or not items:
                break

    components = components[:limit]
    return json.dumps([{
        "id": comp.get("id", ""),
        "repository": comp.get("repository", ""),
        "format": comp.get("format", ""),
        "group": comp.get("group", ""),
        "name": comp.get("name", ""),
        "version": comp.get("version", ""),
        "download_url": comp.get("downloadUrl", ""),
        "path": comp.get("path", ""),
        "content_type": comp.get("contentType", ""),
        "last_modified": comp.get("lastModified", ""),
        "size": comp.get("fileSize", 0),
    } for comp in components], indent=2)


@mcp.tool()
def list_assets(repository: str, limit: int = 30) -> str:
    """List assets in a specific repository.

    Args:
        repository: Repository name
        limit: Max results (default 30)
    """
    assets = []
    continuation_token = None
    params: dict = {"repository": repository}

    with _client() as c:
        while len(assets) < limit:
            if continuation_token:
                params["continuationToken"] = continuation_token
            r = c.get("/assets", params=params)
            r.raise_for_status()
            data = r.json()
            items = data.get("items", [])
            assets.extend(items)
            continuation_token = data.get("continuationToken")
            if not continuation_token or not items:
                break

    assets = assets[:limit]
    return json.dumps([{
        "id": a.get("id", ""),
        "path": a.get("path", ""),
        "repository": a.get("repository", ""),
        "format": a.get("format", ""),
        "content_type": a.get("contentType", ""),
        "size": a.get("fileSize", 0),
        "last_modified": a.get("lastModified", ""),
        "download_url": a.get("downloadUrl", ""),
        "checksum_sha1": a.get("checksum", {}).get("sha1", ""),
    } for a in assets], indent=2)


@mcp.tool()
def get_asset(asset_id: str) -> str:
    """Get details for a specific asset.

    Args:
        asset_id: Asset ID (from list_assets or search_components)
    """
    with _client() as c:
        r = c.get(f"/assets/{asset_id}")
        r.raise_for_status()
        a = r.json()
    return json.dumps({
        "id": a.get("id", ""),
        "path": a.get("path", ""),
        "repository": a.get("repository", ""),
        "format": a.get("format", ""),
        "content_type": a.get("contentType", ""),
        "size": a.get("fileSize", 0),
        "last_modified": a.get("lastModified", ""),
        "download_url": a.get("downloadUrl", ""),
        "checksum": a.get("checksum", {}),
    }, indent=2)


@mcp.tool()
def search_component_versions(repository: str, group: str, name: str) -> str:
    """List all available versions of a component.

    Args:
        repository: Repository name
        group: Maven groupId (e.g. com.example) or npm scope
        name: Artifact name / artifactId
    """
    params: dict = {"repository": repository, "group": group, "name": name}
    versions = []
    continuation_token = None

    with _client() as c:
        while True:
            if continuation_token:
                params["continuationToken"] = continuation_token
            r = c.get("/search", params=params)
            r.raise_for_status()
            data = r.json()
            items = data.get("items", [])
            for item in items:
                v = item.get("version", "")
                if v and v not in versions:
                    versions.append(v)
            continuation_token = data.get("continuationToken")
            if not continuation_token:
                break

    return json.dumps({
        "repository": repository,
        "group": group,
        "name": name,
        "versions": versions,
        "count": len(versions),
    }, indent=2)


@mcp.tool()
def get_status() -> str:
    """Get Nexus server status and version info."""
    with _client() as c:
        r = c.get("/status")
        r.raise_for_status()
    return json.dumps({"status": r.status_code, "available": r.status_code == 200}, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
