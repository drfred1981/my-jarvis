"""Per-conversation skill attachments for the skills MCP.

Attaching a skill to a conversation gives that conversation its own competency:
the dispatcher injector then surfaces the skill's full content in that
conversation only. Stored on the shared memory NFS so the injector (a separate
process) reads the same source of truth:

    <JARVIS_MEMORY_DIR>/skill-attachments/<key with ':'→'-'>.json
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import catalog

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(os.getenv("JARVIS_MEMORY_DIR", "/home/jarvis/memory"))
ATTACH_DIR = MEMORY_DIR / "skill-attachments"


def _file(key: str) -> Path:
    return ATTACH_DIR / f"{key.replace(':', '-')}.json"


def _read(key: str) -> list[str]:
    f = _file(key)
    if not f.is_file():
        return []
    try:
        return list(json.loads(f.read_text(encoding="utf-8")).get("skills", []))
    except (OSError, json.JSONDecodeError):
        return []


def _write(key: str, names: list[str]) -> None:
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    _file(key).write_text(json.dumps({"skills": names}, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def attach(key: str, name: str) -> dict:
    if not catalog.skill_path(name).is_file():
        return {"error": f"unknown skill '{name}' — create_skill first"}
    names = _read(key)
    if name not in names:
        names.append(name)
        _write(key, names)
    return {"ok": True, "conversation": key, "skills": names}


def detach(key: str, name: str) -> dict:
    names = [n for n in _read(key) if n != name]
    _write(key, names)
    return {"ok": True, "conversation": key, "skills": names}


def list_for(key: str) -> dict:
    return {"conversation": key, "skills": _read(key)}
