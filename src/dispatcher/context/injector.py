"""Local + global context injection.

Before each turn, the dispatcher prepends a bounded context block read directly
from the memory NFS store (the same `.md` files the `memory` MCP writes), so a
conversation benefits from:

  - its *local* distilled context : ``conversations/<key>``
  - the *global* perimeter        : ``global/state``

…without spending an MCP tool call per turn. Missing files produce no block, so
injection is a zero-cost no-op until introspection / the agent start writing
those contexts (Phase 3 doctrine). The reader replicates the memory MCP slug
rules just enough to resolve files; keys are mapped to slug-safe names so the
two sides agree deterministically.
"""

from __future__ import annotations

import logging
import os

from conversations import keys

from . import skills

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.realpath(os.getenv("JARVIS_MEMORY_DIR", "/home/jarvis/memory"))

# Memory context holding the synthesized whole-perimeter view (maintained by the
# deep introspection cycle, Phase 2/3).
GLOBAL_CONTEXT_NAME = "global/state"

# Caps to keep the prompt bounded (characters).
MAX_GLOBAL_CHARS = 4000
MAX_LOCAL_CHARS = 4000


def local_context_name(key: str) -> str:
    """Memory context name holding a conversation's distilled local context.

    Conversation keys use ':' separators; memory context names are path-like and
    slug-safe, so ':' is mapped to '-' (e.g. ``discord:dm:1`` →
    ``conversations/discord-dm-1``). Phase 3 doctrine instructs the agent to save
    under this exact name so reads and writes line up.
    """
    return "conversations/" + key.replace(keys.SEP, "-")


def _context_path(name: str) -> str:
    """Resolve a memory context name to its .md file under MEMORY_DIR.

    Returns "" if the resolved path escapes MEMORY_DIR (defensive against keys
    crafted with traversal sequences).
    """
    rel = [seg for seg in name.strip("/").split("/") if seg]
    if not rel:
        return ""
    path = os.path.realpath(os.path.join(MEMORY_DIR, *rel) + ".md")
    if path != MEMORY_DIR and not path.startswith(MEMORY_DIR + os.sep):
        logger.warning("context: rejected out-of-tree name %r", name)
        return ""
    return path


def _read_capped(name: str, max_chars: int) -> str:
    path = _context_path(name)
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError as e:
        logger.warning("context: cannot read %s: %s", path, e)
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…(tronqué)"
    return text


def build_block(key: str) -> str:
    """Assemble the injected context block for a key ("" when nothing to inject).

    - Global context + global skill catalog: any user / introspection conversation.
    - Local context + attached skills: real user conversations only.
    """
    sections = []
    wants_skills = keys.is_user(key) or key == keys.INTROSPECTION

    global_ctx = _read_capped(GLOBAL_CONTEXT_NAME, MAX_GLOBAL_CHARS)
    if global_ctx:
        sections.append("## Contexte global (périmètre)\n" + global_ctx)

    if wants_skills:
        catalog = skills.catalog_block()
        if catalog:
            sections.append(catalog)

    if keys.is_user(key):
        local_ctx = _read_capped(local_context_name(key), MAX_LOCAL_CHARS)
        if local_ctx:
            sections.append("## Contexte local (cette conversation)\n" + local_ctx)
        attached = skills.attached_block(key)
        if attached:
            sections.append(attached)

    if not sections:
        return ""

    header = ""
    if keys.is_user(key):
        header = (f"Conversation `{key}` — mémoire locale `{local_context_name(key)}` "
                  "(`memory:save_context` pour persister ; attache des compétences via le "
                  "MCP `skills`).\n\n")

    return "<!-- contexte injecté automatiquement -->\n" + header + "\n\n".join(sections)


def inject(key: str, message: str) -> str:
    """Prepend the context block to a message (unchanged when no context)."""
    block = build_block(key)
    return f"{block}\n\n---\n\n{message}" if block else message
