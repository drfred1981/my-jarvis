"""MCP Server for context-scoped persistent memory.

Memory is stored as Markdown files in `JARVIS_MEMORY_DIR` (default:
`/home/jarvis/memory`). The directory lives on the NFS PVC so it
survives pod restarts.

Layout:
    <memory_dir>/
        INDEX.md                    ← short pointer list of all contexts
        <context>.md                ← one file per top-level context
        apps/<app>.md               ← per-application notes
        digest/<YYYY-MM-DD>.md      ← daily proactive digests
        repos/<repo>.md             ← last seen state per repo (commits, branches)

A "context" is just a logical slug: 'planka', 'apps-k8s', 'cluster',
'paperdms', 'home-assistant', 'incidents', 'preferences', etc.
"""

import datetime as _dt
import json
import logging
import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("memory")

MEMORY_DIR = Path(os.getenv("JARVIS_MEMORY_DIR", "/home/jarvis/memory")).resolve()
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

INDEX_FILE = MEMORY_DIR / "INDEX.md"

_SLUG_RE = re.compile(r"[^a-z0-9._/-]+")


def _slug(value: str) -> str:
    """Normalize a context name into a safe filename slug."""
    value = value.strip().lower().replace(" ", "-")
    value = _SLUG_RE.sub("-", value)
    return value.strip("-/.") or "untitled"


def _path_for(context: str) -> Path:
    """Resolve the file path for a context name, sandboxed to MEMORY_DIR."""
    slug = _slug(context)
    if not slug.endswith(".md"):
        slug += ".md"
    target = (MEMORY_DIR / slug).resolve()
    # Sandbox: refuse path escape
    if MEMORY_DIR not in target.parents and target != MEMORY_DIR:
        raise ValueError(f"refusing path escape: {context}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _refresh_index() -> None:
    """Regenerate INDEX.md with one line per memory file."""
    entries = []
    for p in sorted(MEMORY_DIR.rglob("*.md")):
        if p.name == "INDEX.md":
            continue
        rel = p.relative_to(MEMORY_DIR).as_posix()
        first_heading = ""
        try:
            with p.open() as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("# "):
                        first_heading = line[2:].strip()
                        break
                    if line and not line.startswith("---"):
                        first_heading = line[:120]
                        break
        except OSError:
            pass
        entries.append(f"- [{rel}]({rel}) — {first_heading or '(empty)'}")
    INDEX_FILE.write_text(
        "# Memory index\n\n"
        f"_Auto-regenerated. Root: `{MEMORY_DIR}`. {len(entries)} files._\n\n"
        + "\n".join(entries) + "\n"
    )


@mcp.tool()
def list_contexts() -> str:
    """List every memory context with its path and one-line summary."""
    _refresh_index()
    contexts = []
    for p in sorted(MEMORY_DIR.rglob("*.md")):
        if p.name == "INDEX.md":
            continue
        rel = p.relative_to(MEMORY_DIR).as_posix()
        stat = p.stat()
        contexts.append({
            "context": rel.removesuffix(".md"),
            "path": str(p),
            "size_bytes": stat.st_size,
            "last_modified": _dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return json.dumps(contexts, indent=2, ensure_ascii=False)


@mcp.tool()
def load_context(context: str) -> str:
    """Load a memory context (returns the full Markdown content).

    Args:
        context: Context name, e.g. 'planka', 'cluster', 'apps/paperdms',
                 'digest/2026-05-12', 'repos/apps-in-k8s', 'preferences'.
    """
    path = _path_for(context)
    if not path.exists():
        return json.dumps({"context": context, "path": str(path), "content": None,
                           "note": "context does not exist yet"}, indent=2)
    return json.dumps({"context": context, "path": str(path),
                       "content": path.read_text()}, indent=2, ensure_ascii=False)


@mcp.tool()
def save_context(context: str, content: str) -> str:
    """Replace the full content of a memory context.

    Args:
        context: Context name (see list_contexts).
        content: New Markdown content (replaces existing).
    """
    path = _path_for(context)
    path.write_text(content)
    _refresh_index()
    return json.dumps({"status": "saved", "context": context, "path": str(path),
                       "bytes": len(content)}, indent=2)


@mcp.tool()
def append_to_context(context: str, content: str, heading: str = "") -> str:
    """Append content to a memory context. If `heading` is given, a `## heading <ts>`
    section is added; otherwise content is appended directly with a separator.

    Args:
        context: Context name.
        content: Markdown to append.
        heading: Optional H2 heading (a timestamp is suffixed).
    """
    path = _path_for(context)
    ts = _dt.datetime.now().isoformat(timespec="minutes")
    block = ""
    if not path.exists():
        block += f"# {context}\n\n"
    if heading:
        block += f"\n## {heading} — {ts}\n\n"
    else:
        block += f"\n<!-- appended {ts} -->\n\n"
    block += content.rstrip() + "\n"
    with path.open("a") as f:
        f.write(block)
    _refresh_index()
    return json.dumps({"status": "appended", "context": context, "path": str(path),
                       "added_bytes": len(block)}, indent=2)


@mcp.tool()
def delete_context(context: str) -> str:
    """Delete a memory context file (does not delete subdirectories).

    Args:
        context: Context name.
    """
    path = _path_for(context)
    if not path.exists():
        return json.dumps({"status": "noop", "context": context, "reason": "not found"})
    path.unlink()
    _refresh_index()
    return json.dumps({"status": "deleted", "context": context, "path": str(path)})


@mcp.tool()
def search_memory(query: str, limit: int = 20) -> str:
    """Case-insensitive substring search across every memory context.

    Args:
        query: Search term (literal substring, not a regex).
        limit: Max matching lines to return.
    """
    needle = query.lower()
    hits: list[dict] = []
    for p in sorted(MEMORY_DIR.rglob("*.md")):
        if p.name == "INDEX.md":
            continue
        try:
            with p.open() as f:
                for i, line in enumerate(f, 1):
                    if needle in line.lower():
                        hits.append({
                            "context": p.relative_to(MEMORY_DIR).as_posix().removesuffix(".md"),
                            "line": i,
                            "text": line.rstrip(),
                        })
                        if len(hits) >= limit:
                            return json.dumps(hits, indent=2, ensure_ascii=False)
        except OSError:
            continue
    return json.dumps(hits, indent=2, ensure_ascii=False)


@mcp.tool()
def get_index() -> str:
    """Return the auto-generated index (INDEX.md content)."""
    _refresh_index()
    return INDEX_FILE.read_text()


if __name__ == "__main__":
    mcp.run(transport="stdio")
