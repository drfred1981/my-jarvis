"""MCP Server for Homebox (home inventory management).

Provides tools to interact with Homebox via its REST API:
- Search and browse inventory items
- Manage locations (rooms, storage areas) and labels
- Track maintenance logs on items
- View inventory statistics
- Export inventory

Requires env vars:
  HOMEBOX_URL=http://homebox.local:7745
  HOMEBOX_USER=user@example.com
  HOMEBOX_PASSWORD=secret
"""

import json
import logging
import os
import threading

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("homebox")

HOMEBOX_URL = os.getenv("HOMEBOX_URL", "").rstrip("/")
HOMEBOX_USER = os.getenv("HOMEBOX_USER", "")
HOMEBOX_PASSWORD = os.getenv("HOMEBOX_PASSWORD", "")

# Token management
_token: str = ""
_token_lock = threading.Lock()


def _login() -> str:
    """Authenticate to Homebox and return bearer token."""
    global _token
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{HOMEBOX_URL}/api/v1/users/login",
            json={"username": HOMEBOX_USER, "password": HOMEBOX_PASSWORD},
        )
        resp.raise_for_status()
        data = resp.json()
    _token = data.get("token", "")
    if not _token:
        raise RuntimeError(f"Homebox login failed: no token in response")
    return _token


def _get_token() -> str:
    """Get a valid bearer token, logging in if needed."""
    global _token
    with _token_lock:
        if not _token:
            _login()
        return _token


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=HOMEBOX_URL, headers=_headers(), timeout=30)


def _api_call(method: str, path: str, **kwargs) -> httpx.Response:
    """Make an API call with automatic re-auth on 401."""
    global _token
    with _client() as client:
        resp = getattr(client, method)(path, **kwargs)

    if resp.status_code == 401:
        with _token_lock:
            _login()
        with _client() as client:
            resp = getattr(client, method)(path, **kwargs)

    resp.raise_for_status()
    return resp


@mcp.tool()
def search_items(query: str = "", location_id: str = "", label_id: str = "", page: int = 1, page_size: int = 50) -> str:
    """Search and list inventory items with optional filters.

    Args:
        query: Text search in item names and descriptions
        location_id: Filter by location ID (from list_locations)
        label_id: Filter by label ID (from list_labels)
        page: Page number (default: 1)
        page_size: Items per page (default: 50)
    """
    params: dict = {"page": page, "pageSize": page_size}
    if query:
        params["q"] = query
    if location_id:
        params["locations[]"] = location_id
    if label_id:
        params["labels[]"] = label_id

    resp = _api_call("get", "/api/v1/items", params=params)
    data = resp.json()

    items = []
    for item in data.get("items", []):
        items.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "description": item.get("description", ""),
            "quantity": item.get("quantity", 1),
            "location": item.get("location", {}).get("name", ""),
            "labels": [l.get("name", "") for l in item.get("labels", [])],
            "purchase_price": item.get("purchasePrice"),
        })

    return json.dumps({
        "query": query,
        "page": page,
        "count": len(items),
        "items": items,
    }, indent=2)


@mcp.tool()
def get_item(item_id: str) -> str:
    """Get detailed information about a specific inventory item.

    Args:
        item_id: Item UUID (from search_items)
    """
    resp = _api_call("get", f"/api/v1/items/{item_id}")
    item = resp.json()

    return json.dumps({
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description"),
        "quantity": item.get("quantity"),
        "location": item.get("location", {}).get("name", ""),
        "labels": [l.get("name", "") for l in item.get("labels", [])],
        "purchase_price": item.get("purchasePrice"),
        "purchase_date": item.get("purchaseFrom"),
        "warranty_expires": item.get("warrantyExpires"),
        "serial_number": item.get("serialNumber", ""),
        "model_number": item.get("modelNumber", ""),
        "manufacturer": item.get("manufacturer", ""),
        "asset_id": item.get("assetId", ""),
        "notes": item.get("notes", ""),
        "custom_fields": item.get("fields", []),
        "attachments": len(item.get("attachments", [])),
    }, indent=2)


@mcp.tool()
def list_locations() -> str:
    """List all locations (rooms, storage areas) as a tree hierarchy."""
    resp = _api_call("get", "/api/v1/locations/tree")
    locations = resp.json()

    def flatten(loc_list, depth=0):
        result = []
        for loc in loc_list:
            result.append({
                "id": loc.get("id"),
                "name": loc.get("name"),
                "depth": depth,
                "item_count": loc.get("itemCount", 0),
            })
            for child in loc.get("children", []):
                result.extend(flatten([child], depth + 1))
        return result

    flat = flatten(locations)
    return json.dumps({"count": len(flat), "locations": flat}, indent=2)


@mcp.tool()
def list_labels() -> str:
    """List all labels/tags used for organizing items."""
    resp = _api_call("get", "/api/v1/labels")
    labels = resp.json()

    result = []
    for label in labels:
        result.append({
            "id": label.get("id"),
            "name": label.get("name"),
            "description": label.get("description", ""),
            "item_count": label.get("itemCount", 0),
        })
    return json.dumps({"count": len(result), "labels": result}, indent=2)


@mcp.tool()
def get_statistics() -> str:
    """Get inventory statistics overview (total items, value, by location and label)."""
    resp_general = _api_call("get", "/api/v1/groups/statistics")
    general = resp_general.json()

    resp_locations = _api_call("get", "/api/v1/groups/statistics/locations")
    by_location = resp_locations.json()

    resp_labels = _api_call("get", "/api/v1/groups/statistics/labels")
    by_label = resp_labels.json()

    return json.dumps({
        "overview": general,
        "by_location": by_location,
        "by_label": by_label,
    }, indent=2)


@mcp.tool()
def get_maintenance_log(item_id: str) -> str:
    """Get maintenance history for an item.

    Args:
        item_id: Item UUID
    """
    resp = _api_call("get", f"/api/v1/items/{item_id}/maintenance")
    entries = resp.json()

    result = []
    for entry in entries:
        result.append({
            "id": entry.get("id"),
            "date": entry.get("date"),
            "name": entry.get("name", ""),
            "description": entry.get("description", ""),
            "cost": entry.get("cost", 0),
        })
    return json.dumps({"item_id": item_id, "count": len(result), "entries": result}, indent=2)


@mcp.tool()
def add_maintenance_log(item_id: str, name: str, date: str, description: str = "", cost: float = 0) -> str:
    """Add a maintenance log entry to an item.

    Args:
        item_id: Item UUID
        name: Maintenance title (e.g. "Battery replacement")
        date: Date of maintenance (YYYY-MM-DD)
        description: Details of the maintenance
        cost: Cost of maintenance
    """
    payload = {
        "name": name,
        "date": date,
        "description": description,
        "cost": cost,
    }
    resp = _api_call("post", f"/api/v1/items/{item_id}/maintenance", json=payload)
    entry = resp.json()
    return json.dumps({"status": "ok", "entry_id": entry.get("id"), "item_id": item_id}, indent=2)


@mcp.tool()
def get_status() -> str:
    """Get Homebox server health and version."""
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{HOMEBOX_URL}/api/v1/status")
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
