"""Skill library for the skills MCP: list / read / create SKILL.md files.

Skills are Markdown procedures under ``JARVIS_SKILLS_DIR`` (default
``/home/jarvis/skills``), hot-reloaded each agent turn. ``create_skill`` is the
agent's self-improvement primitive: when a competency is missing, it authors one
and it becomes available immediately.

Imported flat (``import catalog``): the MCP server runs as a script.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(os.getenv("JARVIS_SKILLS_DIR", "/home/jarvis/skills"))

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _parse_frontmatter(text: str) -> dict:
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


def skill_path(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


def list_skills() -> list[dict]:
    out: list[dict] = []
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
        out.append({"name": meta.get("name", d.name),
                    "description": meta.get("description", ""),
                    "dir": d.name,
                    "tools": meta.get("tools", "")})
    return out


def read_skill(name: str) -> dict:
    f = skill_path(name)
    if not f.is_file():
        return {"error": f"unknown skill '{name}'"}
    return {"ok": True, "name": name, "content": f.read_text(encoding="utf-8")}


def create_skill(name: str, description: str, content: str, tools: str = "") -> dict:
    """Create/overwrite a skill `<SKILLS_DIR>/<name>/SKILL.md` (hot-reloaded)."""
    if not _NAME_RE.match(name):
        return {"error": "name must be kebab-case ([a-z0-9-], starting alnum)"}
    if not description.strip():
        return {"error": "description is required (used to decide relevance)"}

    fm = f"---\nname: {name}\ndescription: {description.strip()}\n"
    if tools.strip():
        fm += f"tools: {tools.strip()}\n"
    fm += "---\n\n"
    body = content if content.lstrip().startswith("#") else f"# {name}\n\n{content}"

    path = skill_path(name)
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fm + body.strip() + "\n", encoding="utf-8")
    logger.info("Skill %s %s", name, "updated" if existed else "created")
    return {
        "ok": True,
        "name": name,
        "path": str(path),
        "updated": existed,
        "persist_hint": (
            "Disponible immédiatement (runtime, sur le volume). Ce skill n'est PAS "
            "versionné dans le code. S'il a vocation à durer, propose-le à ton repo "
            f"via git-write : skills/{name}/SKILL.md (revue humaine → re-livré à chaque "
            "image). Voir le skill `skill-authoring`."
        ),
    }
