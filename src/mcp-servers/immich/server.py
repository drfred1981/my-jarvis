"""MCP Server for Immich (photo/video management).

Provides tools to search, browse, and manage photos/videos via Immich API.
API docs: https://immich.app/docs/api/
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("immich")

IMMICH_URL = os.getenv("IMMICH_URL", "http://immich.default.svc.cluster.local:2283")
IMMICH_API_KEY = os.getenv("IMMICH_API_KEY", "")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=IMMICH_URL,
        headers={"x-api-key": IMMICH_API_KEY},
        timeout=30,
    )


@mcp.tool()
def get_server_stats() -> str:
    """Get Immich server statistics (photos, videos, storage usage)."""
    with _client() as client:
        resp = client.get("/api/servers/statistics")
        resp.raise_for_status()
        stats = resp.json()
    return json.dumps(stats, indent=2)


@mcp.tool()
def get_server_info() -> str:
    """Get Immich server version and configuration info."""
    with _client() as client:
        resp = client.get("/api/servers/about")
        resp.raise_for_status()
        info = resp.json()
    return json.dumps(info, indent=2)


@mcp.tool()
def search_assets(query: str, type: str = "", limit: int = 20) -> str:
    """Search photos and videos by text (smart search / CLIP).

    Args:
        query: Search text (e.g. "sunset", "cat", "birthday party")
        type: Filter by type: "IMAGE" or "VIDEO" (empty for all)
        limit: Max results (default: 20)
    """
    payload = {"query": query, "size": limit}
    if type:
        payload["type"] = type

    with _client() as client:
        resp = client.post("/api/search/smart", json=payload)
        resp.raise_for_status()
        data = resp.json()

    assets = data.get("assets", {}).get("items", [])
    return json.dumps({
        "count": len(assets),
        "assets": [{
            "id": a["id"],
            "type": a.get("type"),
            "filename": a.get("originalFileName", ""),
            "date": a.get("fileCreatedAt", ""),
            "city": a.get("exifInfo", {}).get("city", ""),
            "country": a.get("exifInfo", {}).get("country", ""),
            "description": a.get("exifInfo", {}).get("description", ""),
        } for a in assets],
    }, indent=2)


@mcp.tool()
def search_metadata(
    city: str = "",
    country: str = "",
    make: str = "",
    model: str = "",
    taken_after: str = "",
    taken_before: str = "",
    limit: int = 20,
) -> str:
    """Search assets by metadata (location, camera, date range).

    Args:
        city: Filter by city name
        country: Filter by country name
        make: Filter by camera make (e.g. "Apple", "Canon")
        model: Filter by camera model
        taken_after: ISO date - photos taken after this date
        taken_before: ISO date - photos taken before this date
        limit: Max results (default: 20)
    """
    payload = {"size": limit}
    if city:
        payload["city"] = city
    if country:
        payload["country"] = country
    if make:
        payload["make"] = make
    if model:
        payload["model"] = model
    if taken_after:
        payload["takenAfter"] = taken_after
    if taken_before:
        payload["takenBefore"] = taken_before

    with _client() as client:
        resp = client.post("/api/search/metadata", json=payload)
        resp.raise_for_status()
        data = resp.json()

    assets = data.get("assets", {}).get("items", [])
    return json.dumps({
        "count": len(assets),
        "assets": [{
            "id": a["id"],
            "type": a.get("type"),
            "filename": a.get("originalFileName", ""),
            "date": a.get("fileCreatedAt", ""),
        } for a in assets],
    }, indent=2)


@mcp.tool()
def list_albums(shared: bool = False) -> str:
    """List all albums.

    Args:
        shared: If true, only list shared albums
    """
    with _client() as client:
        params = {"shared": str(shared).lower()}
        resp = client.get("/api/albums", params=params)
        resp.raise_for_status()
        albums = resp.json()
    return json.dumps([{
        "id": a["id"],
        "name": a.get("albumName", ""),
        "asset_count": a.get("assetCount", 0),
        "shared": a.get("shared", False),
        "created_at": a.get("createdAt", ""),
        "updated_at": a.get("updatedAt", ""),
    } for a in albums], indent=2)


@mcp.tool()
def get_album(album_id: str) -> str:
    """Get album details with its assets.

    Args:
        album_id: Album ID
    """
    with _client() as client:
        resp = client.get(f"/api/albums/{album_id}")
        resp.raise_for_status()
        album = resp.json()

    assets = album.get("assets", [])
    return json.dumps({
        "id": album["id"],
        "name": album.get("albumName", ""),
        "description": album.get("description", ""),
        "asset_count": album.get("assetCount", 0),
        "shared": album.get("shared", False),
        "assets": [{
            "id": a["id"],
            "type": a.get("type"),
            "filename": a.get("originalFileName", ""),
            "date": a.get("fileCreatedAt", ""),
        } for a in assets[:50]],  # Limit to first 50
    }, indent=2)


@mcp.tool()
def get_asset_info(asset_id: str) -> str:
    """Get detailed info about a specific asset (photo/video).

    Args:
        asset_id: Asset ID
    """
    with _client() as client:
        resp = client.get(f"/api/assets/{asset_id}")
        resp.raise_for_status()
        asset = resp.json()
    exif = asset.get("exifInfo", {})
    return json.dumps({
        "id": asset["id"],
        "type": asset.get("type"),
        "filename": asset.get("originalFileName", ""),
        "file_size": asset.get("exifInfo", {}).get("fileSizeInByte"),
        "date": asset.get("fileCreatedAt", ""),
        "width": exif.get("exifImageWidth"),
        "height": exif.get("exifImageHeight"),
        "camera": f"{exif.get('make', '')} {exif.get('model', '')}".strip(),
        "lens": exif.get("lensModel", ""),
        "location": {
            "city": exif.get("city", ""),
            "state": exif.get("state", ""),
            "country": exif.get("country", ""),
            "latitude": exif.get("latitude"),
            "longitude": exif.get("longitude"),
        },
        "description": exif.get("description", ""),
        "is_favorite": asset.get("isFavorite", False),
    }, indent=2)


@mcp.tool()
def list_people() -> str:
    """List recognized people (face recognition)."""
    with _client() as client:
        resp = client.get("/api/people")
        resp.raise_for_status()
        data = resp.json()

    people = data.get("people", [])
    return json.dumps([{
        "id": p["id"],
        "name": p.get("name", ""),
        "thumbnail_path": p.get("thumbnailPath", ""),
        "asset_count": p.get("assetCount", 0),
    } for p in people if p.get("name")], indent=2)


@mcp.tool()
def get_timeline_stats() -> str:
    """Get a summary of assets grouped by date."""
    with _client() as client:
        resp = client.get("/api/assets/statistics")
        resp.raise_for_status()
        stats = resp.json()
    return json.dumps(stats, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
