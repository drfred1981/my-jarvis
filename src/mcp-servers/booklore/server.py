"""MCP Server for Booklore (self-hosted ebook / book library manager).

Provides read & write access to books, libraries, shelves, authors,
series, categories, reading progress and stats.

Auth: POST /api/v1/auth/login -> JWT (cached in module state, refreshed on 401).
Env vars:
    BOOKLORE_URL       (e.g. http://booklore.home.svc.cluster.local:6060)
    BOOKLORE_USER
    BOOKLORE_PASSWORD
"""

import json
import logging
import os
import threading
import time

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("booklore")

BOOKLORE_URL = os.getenv("BOOKLORE_URL", "").rstrip("/")
BOOKLORE_USER = os.getenv("BOOKLORE_USER", "")
BOOKLORE_PASSWORD = os.getenv("BOOKLORE_PASSWORD", "")

_token: dict = {"value": None, "expires_at": 0.0}
_token_lock = threading.Lock()


def _login() -> str:
    """Authenticate against Booklore and return a JWT token."""
    if not BOOKLORE_URL or not BOOKLORE_USER or not BOOKLORE_PASSWORD:
        raise RuntimeError("BOOKLORE_URL / BOOKLORE_USER / BOOKLORE_PASSWORD must be set")

    with httpx.Client(base_url=BOOKLORE_URL, timeout=30) as c:
        resp = c.post(
            "/api/v1/auth/login",
            json={"username": BOOKLORE_USER, "password": BOOKLORE_PASSWORD},
        )
        resp.raise_for_status()
        data = resp.json()
    token = data.get("accessToken") or data.get("token") or data.get("jwt") or data.get("access_token")
    if not token:
        raise RuntimeError(f"Booklore login response missing token field: {list(data.keys())}")
    # Cache for ~50 min (typical JWT validity 1h)
    _token["value"] = token
    _token["expires_at"] = time.time() + 50 * 60
    return token


def _get_token() -> str:
    with _token_lock:
        if not _token["value"] or time.time() >= _token["expires_at"]:
            return _login()
        return _token["value"]


def _client() -> httpx.Client:
    token = _get_token()
    return httpx.Client(
        base_url=BOOKLORE_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """HTTP request with automatic JWT refresh on 401."""
    with _client() as c:
        resp = c.request(method, path, **kwargs)
    if resp.status_code == 401:
        with _token_lock:
            _token["value"] = None
        with _client() as c:
            resp = c.request(method, path, **kwargs)
    resp.raise_for_status()
    return resp


def _short_book(b: dict) -> dict:
    return {
        "id": b.get("id"),
        "title": b.get("title") or b.get("metadata", {}).get("title", ""),
        "authors": b.get("authors") or b.get("metadata", {}).get("authors", []),
        "series": b.get("seriesName") or b.get("metadata", {}).get("seriesName", ""),
        "series_index": b.get("seriesIndex") or b.get("metadata", {}).get("seriesIndex"),
        "categories": b.get("categories") or b.get("metadata", {}).get("categories", []),
        "language": b.get("language") or b.get("metadata", {}).get("language", ""),
        "page_count": b.get("pageCount") or b.get("metadata", {}).get("pageCount"),
        "rating": b.get("rating") or b.get("metadata", {}).get("rating"),
        "read_status": b.get("readStatus") or b.get("readingStatus"),
        "progress": b.get("progressPercentage") or b.get("readProgress", {}).get("percentage"),
        "library_id": b.get("libraryId"),
        "shelves": [s.get("name") for s in (b.get("shelves") or []) if isinstance(s, dict)],
        "added_on": b.get("addedOn") or b.get("createdAt"),
    }


# --------------------------------------------------------------------- Books

@mcp.tool()
def list_books(limit: int = 25, library_id: str = "", shelf_id: str = "",
               read_status: str = "", sort: str = "addedOn,desc") -> str:
    """List books, optionally filtered.

    Args:
        limit: Max results (default 25)
        library_id: Restrict to a library (optional)
        shelf_id: Restrict to a shelf (optional)
        read_status: UNREAD | READING | READ (optional)
        sort: Field,direction (default 'addedOn,desc')
    """
    params: dict = {"size": limit, "sort": sort}
    if library_id:
        params["libraryId"] = library_id
    if shelf_id:
        params["shelfId"] = shelf_id
    if read_status:
        params["readStatus"] = read_status
    resp = _request("GET", "/api/v1/books", params=params)
    data = resp.json()
    items = data.get("content") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    return json.dumps([_short_book(b) for b in items], indent=2, ensure_ascii=False)


@mcp.tool()
def search_books(query: str, limit: int = 25) -> str:
    """Full-text search across books (title, author, series, description).

    Args:
        query: Search query
        limit: Max results
    """
    resp = _request("GET", "/api/v1/books/search", params={"q": query, "size": limit})
    data = resp.json()
    items = data.get("content") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    return json.dumps([_short_book(b) for b in items], indent=2, ensure_ascii=False)


@mcp.tool()
def get_book(book_id: str) -> str:
    """Get full metadata of a book.

    Args:
        book_id: Book ID
    """
    resp = _request("GET", f"/api/v1/books/{book_id}")
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def update_book_metadata(book_id: str, title: str = "", authors: str = "", series: str = "",
                          series_index: float = 0, categories: str = "", description: str = "",
                          language: str = "", rating: int = 0) -> str:
    """Update editable metadata of a book (only provided fields are sent).

    Args:
        book_id: Book ID
        title: New title (optional)
        authors: Comma-separated author names (optional)
        series: Series name (optional)
        series_index: Position in series (optional, 0 = ignored)
        categories: Comma-separated categories (optional)
        description: Description (optional)
        language: ISO language code, e.g. 'fr' (optional)
        rating: 1..5 (optional, 0 = ignored)
    """
    payload: dict = {}
    if title:
        payload["title"] = title
    if authors:
        payload["authors"] = [a.strip() for a in authors.split(",") if a.strip()]
    if series:
        payload["seriesName"] = series
    if series_index:
        payload["seriesIndex"] = series_index
    if categories:
        payload["categories"] = [c.strip() for c in categories.split(",") if c.strip()]
    if description:
        payload["description"] = description
    if language:
        payload["language"] = language
    if rating:
        payload["rating"] = rating

    if not payload:
        return json.dumps({"status": "noop", "reason": "no field provided"})

    resp = _request("PUT", f"/api/v1/books/{book_id}", json=payload)
    return json.dumps({"status": "updated", "id": book_id, "fields": list(payload.keys())},
                       indent=2, ensure_ascii=False)


@mcp.tool()
def trigger_metadata_refresh(book_id: str) -> str:
    """Trigger Booklore's native metadata refresh for a book (Goodreads, cover, etc.).

    Sends a REFRESH_METADATA_MANUAL task to the TaskService. Returns task info
    (taskId, status=ACCEPTED) if successful.

    Args:
        book_id: Book ID to refresh
    """
    payload = {
        "taskType": "REFRESH_METADATA_MANUAL",
        "triggeredByCron": False,
        "options": {
            "refreshType": "BOOKS",
            "bookIds": [int(book_id)],
        },
    }
    resp = _request("POST", "/api/v1/tasks/start", json=payload)
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def get_book_download_url(book_id: str) -> str:
    """Get the URL to download the book file (epub/pdf/etc.).

    Args:
        book_id: Book ID
    """
    # File endpoint is typically protected by JWT; surface the URL + a freshly-minted token hint
    return json.dumps({
        "url": f"{BOOKLORE_URL}/api/v1/books/{book_id}/file",
        "note": "Use Bearer token (Authorization header) to download; the URL is not signed.",
    }, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- Libraries

@mcp.tool()
def list_libraries() -> str:
    """List all libraries (top-level collections that scan folders)."""
    resp = _request("GET", "/api/v1/libraries")
    data = resp.json()
    items = data if isinstance(data, list) else data.get("content", [])
    return json.dumps([{
        "id": l.get("id"),
        "name": l.get("name"),
        "type": l.get("type"),
        "paths": l.get("paths", []),
        "book_count": l.get("bookCount"),
    } for l in items], indent=2, ensure_ascii=False)


@mcp.tool()
def trigger_library_scan(library_id: str) -> str:
    """Trigger a rescan of a library to detect new/changed files.

    Args:
        library_id: Library ID
    """
    resp = _request("POST", f"/api/v1/libraries/{library_id}/scan")
    return json.dumps({"status": "scan_triggered", "library_id": library_id,
                       "http_status": resp.status_code}, indent=2)


# ------------------------------------------------------------------- Shelves

@mcp.tool()
def list_shelves() -> str:
    """List all shelves (user-curated book collections)."""
    resp = _request("GET", "/api/v1/shelves")
    data = resp.json()
    items = data if isinstance(data, list) else data.get("content", [])
    return json.dumps([{
        "id": s.get("id"),
        "name": s.get("name"),
        "icon": s.get("icon"),
        "book_count": s.get("bookCount"),
    } for s in items], indent=2, ensure_ascii=False)


@mcp.tool()
def create_shelf(name: str, icon: str = "") -> str:
    """Create a new shelf.

    Args:
        name: Shelf name
        icon: Icon identifier (optional)
    """
    payload = {"name": name}
    if icon:
        payload["icon"] = icon
    resp = _request("POST", "/api/v1/shelves", json=payload)
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def add_book_to_shelf(shelf_id: str, book_id: str) -> str:
    """Add a book to a shelf.

    Args:
        shelf_id: Shelf ID
        book_id: Book ID
    """
    resp = _request("POST", f"/api/v1/shelves/{shelf_id}/books", json={"bookIds": [book_id]})
    return json.dumps({"status": "added", "shelf_id": shelf_id, "book_id": book_id,
                       "http_status": resp.status_code}, indent=2)


@mcp.tool()
def remove_book_from_shelf(shelf_id: str, book_id: str) -> str:
    """Remove a book from a shelf.

    Args:
        shelf_id: Shelf ID
        book_id: Book ID
    """
    resp = _request("DELETE", f"/api/v1/shelves/{shelf_id}/books/{book_id}")
    return json.dumps({"status": "removed", "shelf_id": shelf_id, "book_id": book_id,
                       "http_status": resp.status_code}, indent=2)


@mcp.tool()
def delete_shelf(shelf_id: str) -> str:
    """Delete a shelf (does not delete the books inside it).

    Args:
        shelf_id: Shelf ID
    """
    resp = _request("DELETE", f"/api/v1/shelves/{shelf_id}")
    return json.dumps({"status": "deleted", "shelf_id": shelf_id,
                       "http_status": resp.status_code}, indent=2)


# -------------------------------------------------------- Authors / Series / Cats

@mcp.tool()
def list_authors(limit: int = 100) -> str:
    """List authors with book counts.

    Args:
        limit: Max results
    """
    resp = _request("GET", "/api/v1/authors", params={"size": limit})
    data = resp.json()
    items = data if isinstance(data, list) else data.get("content", [])
    return json.dumps([{
        "id": a.get("id"),
        "name": a.get("name"),
        "book_count": a.get("bookCount"),
    } for a in items], indent=2, ensure_ascii=False)


@mcp.tool()
def list_series(limit: int = 100) -> str:
    """List series with book counts.

    Args:
        limit: Max results
    """
    resp = _request("GET", "/api/v1/series", params={"size": limit})
    data = resp.json()
    items = data if isinstance(data, list) else data.get("content", [])
    return json.dumps([{
        "id": s.get("id"),
        "name": s.get("name"),
        "book_count": s.get("bookCount"),
    } for s in items], indent=2, ensure_ascii=False)


@mcp.tool()
def list_categories(limit: int = 100) -> str:
    """List categories / tags with book counts.

    Args:
        limit: Max results
    """
    resp = _request("GET", "/api/v1/categories", params={"size": limit})
    data = resp.json()
    items = data if isinstance(data, list) else data.get("content", [])
    return json.dumps([{
        "id": c.get("id"),
        "name": c.get("name"),
        "book_count": c.get("bookCount"),
    } for c in items], indent=2, ensure_ascii=False)


# -------------------------------------------------------------- Reading progress

@mcp.tool()
def get_reading_progress(book_id: str) -> str:
    """Get reading progress for a book (page, percentage, last read).

    Args:
        book_id: Book ID
    """
    resp = _request("GET", f"/api/v1/books/{book_id}/progress")
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def update_reading_progress(book_id: str, page: int = 0, percentage: float = 0.0) -> str:
    """Update reading progress for a book.

    Args:
        book_id: Book ID
        page: Current page (optional)
        percentage: Percentage 0..100 (optional)
    """
    payload: dict = {}
    if page:
        payload["page"] = page
    if percentage:
        payload["percentage"] = percentage
    if not payload:
        return json.dumps({"status": "noop", "reason": "page or percentage required"})
    resp = _request("PUT", f"/api/v1/books/{book_id}/progress", json=payload)
    return json.dumps({"status": "updated", "book_id": book_id, **payload}, indent=2)


@mcp.tool()
def mark_as_read(book_id: str) -> str:
    """Mark a book as fully read (100% progress).

    Args:
        book_id: Book ID
    """
    resp = _request("PUT", f"/api/v1/books/{book_id}/read-status", json={"status": "READ"})
    return json.dumps({"status": "marked_read", "book_id": book_id,
                       "http_status": resp.status_code}, indent=2)


@mcp.tool()
def mark_as_unread(book_id: str) -> str:
    """Mark a book as unread (reset progress).

    Args:
        book_id: Book ID
    """
    resp = _request("PUT", f"/api/v1/books/{book_id}/read-status", json={"status": "UNREAD"})
    return json.dumps({"status": "marked_unread", "book_id": book_id,
                       "http_status": resp.status_code}, indent=2)


# ----------------------------------------------------------------- Stats / views

@mcp.tool()
def list_recent_books(limit: int = 10) -> str:
    """List most recently added books.

    Args:
        limit: Max results
    """
    return list_books(limit=limit, sort="addedOn,desc")


@mcp.tool()
def list_in_progress(limit: int = 20) -> str:
    """List books currently being read.

    Args:
        limit: Max results
    """
    return list_books(limit=limit, read_status="READING")


@mcp.tool()
def list_unread(limit: int = 50) -> str:
    """List unread books.

    Args:
        limit: Max results
    """
    return list_books(limit=limit, read_status="UNREAD")


@mcp.tool()
def get_stats() -> str:
    """Get global library stats: total books, by status, by language, etc."""
    try:
        resp = _request("GET", "/api/v1/stats")
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)
    except httpx.HTTPStatusError:
        # Fallback: count by reading status
        out = {}
        for s in ("UNREAD", "READING", "READ"):
            try:
                r = _request("GET", "/api/v1/books", params={"size": 1, "readStatus": s})
                data = r.json()
                out[s.lower()] = data.get("totalElements", len(data) if isinstance(data, list) else None)
            except Exception:
                out[s.lower()] = None
        return json.dumps(out, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
