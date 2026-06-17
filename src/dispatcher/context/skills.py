"""Read-only skill catalog + per-conversation attachments, for context injection.

Two scopes, both surfaced in the injected context block (see `injector`):

- **Global catalog** — every ``SKILL.md`` under ``JARVIS_SKILLS_DIR`` (name +
  description), injected in every user / introspection conversation so the agent
  always knows its full skill set.
- **Attached skills** — skills explicitly attached to a conversation (managed by
  the `skills` MCP) are injected *in full*, giving that conversation its own
  competencies.

The `skills` MCP is the writer; this module only reads. Both sides agree on:
  - skill library : ``JARVIS_SKILLS_DIR`` (default ``/home/jarvis/skills``)
  - attachments   : ``<JARVIS_MEMORY_DIR>/skill-attachments/<key with ':'→'-'>.json``
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(os.getenv("JARVIS_SKILLS_DIR", "/home/jarvis/skills"))
MEMORY_DIR = Path(os.getenv("JARVIS_MEMORY_DIR", "/home/jarvis/memory"))
ATTACH_DIR = MEMORY_DIR / "skill-attachments"

MAX_CATALOG_CHARS = 2500
MAX_SKILL_CHARS = 2000
MAX_ATTACHED_TOTAL = 6000


def _safe_key(key: str) -> str:
    return key.replace(":", "-")


def _parse_frontmatter(text: str) -> dict:
    """Minimal `key: value` frontmatter parser (no YAML dependency)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip()
    return meta


def _skill_file(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


def list_catalog() -> list[tuple[str, str]]:
    """(name, description) for every skill in the library."""
    out: list[tuple[str, str]] = []
    if not SKILLS_DIR.is_dir():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        try:
            meta = _parse_frontmatter(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        out.append((meta.get("name", d.name), meta.get("description", "")))
    return out


def catalog_block() -> str:
    cat = list_catalog()
    if not cat:
        return ""
    body = "\n".join(f"- **{n}** : {d}" for n, d in cat)
    if len(body) > MAX_CATALOG_CHARS:
        body = body[:MAX_CATALOG_CHARS].rstrip() + "\n…(catalogue tronqué)"
    return ("## Compétences disponibles (skills, globales)\n" + body +
            "\n_Via le MCP `skills` : `attach_skill` pour donner une compétence à cette "
            "conversation, `create_skill` si une compétence te manque._")


def attached_names(key: str) -> list[str]:
    f = ATTACH_DIR / f"{_safe_key(key)}.json"
    if not f.is_file():
        return []
    try:
        return list(json.loads(f.read_text(encoding="utf-8")).get("skills", []))
    except (OSError, json.JSONDecodeError):
        return []


def attached_block(key: str) -> str:
    """Full content of the skills attached to a conversation (capped)."""
    chunks, total = [], 0
    for name in attached_names(key):
        f = _skill_file(name)
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if len(content) > MAX_SKILL_CHARS:
            content = content[:MAX_SKILL_CHARS].rstrip() + "\n…(tronqué)"
        if total + len(content) > MAX_ATTACHED_TOTAL:
            break
        total += len(content)
        chunks.append(f"### Skill: {name}\n{content}")
    if not chunks:
        return ""
    return "## Compétences de cette conversation\n" + "\n\n".join(chunks)
