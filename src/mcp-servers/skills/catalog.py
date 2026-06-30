"""Skill library for the skills MCP: list / read / create SKILL.md files.

Two layers, read as a union (the figé/amendment doctrine):

  - **repo, figé** — ``JARVIS_SKILLS_SEED_DIR`` (default ``/opt/jarvis/seed/skills``),
    the skills shipped in the image. Read-only at runtime; source of truth,
    refreshed on every deploy. **Wins on a name collision.**
  - **runtime, amendment** — ``JARVIS_SKILLS_DIR`` (default ``/home/jarvis/skills``),
    on the persistent volume, where ``create_skill`` writes. Survives restarts,
    layered on top, but can NEVER shadow a repo skill.

``create_skill`` therefore refuses a name that already belongs to the repo: to
change a repo skill you propose a MR (skill ``skill-authoring``), not a runtime
write. Hot-reloaded each agent turn. Imported flat (``import catalog``).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Runtime (writable volume) — amendment layer.
SKILLS_DIR = Path(os.getenv("JARVIS_SKILLS_DIR", "/home/jarvis/skills"))
# Repo (image, read-only) — frozen baseline; wins on name collision.
SEED_SKILLS_DIR = Path(os.getenv("JARVIS_SKILLS_SEED_DIR", "/opt/jarvis/seed/skills"))

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _bases() -> list[Path]:
    """Skill base dirs in precedence order: repo (frozen) first, runtime second."""
    return [SEED_SKILLS_DIR, SKILLS_DIR]


def is_repo_skill(name: str) -> bool:
    """True if `name` is a frozen repo skill (read-only, owns its name)."""
    return (SEED_SKILLS_DIR / name / "SKILL.md").is_file()


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
    """Resolve a skill to its SKILL.md, repo (frozen) taking precedence."""
    for base in _bases():
        p = base / name / "SKILL.md"
        if p.is_file():
            return p
    return SKILLS_DIR / name / "SKILL.md"  # default (may not exist)


def list_skills() -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for base in _bases():
        if not base.is_dir():
            continue
        frozen = base == SEED_SKILLS_DIR
        for d in sorted(base.iterdir()):
            if d.name in seen:
                continue  # repo wins; a runtime skill of the same name is shadowed
            f = d / "SKILL.md"
            if not f.is_file():
                continue
            try:
                meta = _parse_frontmatter(f.read_text(encoding="utf-8"))
            except OSError:
                continue
            seen.add(d.name)
            out.append({"name": meta.get("name", d.name),
                        "description": meta.get("description", ""),
                        "dir": d.name,
                        "tools": meta.get("tools", ""),
                        "source": "repo" if frozen else "runtime",
                        "frozen": frozen})
    return sorted(out, key=lambda s: s["dir"])


def read_skill(name: str) -> dict:
    f = skill_path(name)
    if not f.is_file():
        return {"error": f"unknown skill '{name}'"}
    return {"ok": True, "name": name, "content": f.read_text(encoding="utf-8")}


def create_skill(name: str, description: str, content: str, tools: str = "") -> dict:
    """Create/overwrite a *runtime* skill `<SKILLS_DIR>/<name>/SKILL.md`.

    Refuses a name owned by a repo (frozen) skill: those are versioned and
    authoritative — change them via a MR, never a runtime write.
    """
    if not _NAME_RE.match(name):
        return {"error": "name must be kebab-case ([a-z0-9-], starting alnum)"}
    if not description.strip():
        return {"error": "description is required (used to decide relevance)"}
    if is_repo_skill(name):
        return {"error": (
            f"'{name}' est un skill du repo (figé, versionné, lecture seule au runtime). "
            f"Ne le recrée pas ici : propose une MR sur my-jarvis (skills/{name}/SKILL.md) "
            "via git-write — voir le skill `skill-authoring`.")}

    fm = f"---\nname: {name}\ndescription: {description.strip()}\n"
    if tools.strip():
        fm += f"tools: {tools.strip()}\n"
    fm += "---\n\n"
    body = content if content.lstrip().startswith("#") else f"# {name}\n\n{content}"

    # Always write to the runtime (amendment) layer, never the frozen repo dir.
    path = SKILLS_DIR / name / "SKILL.md"
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fm + body.strip() + "\n", encoding="utf-8")
    logger.info("Runtime skill %s %s", name, "updated" if existed else "created")
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
