"""BMAD capability catalog, for context injection.

Jarvis pilote des repos avec la méthode BMAD (BMad Method + modules) installée
sous ``_bmad/``. Chaque module y déclare ses capacités dans un ``module-help.csv``
(colonnes : ``module,skill,display-name,menu-code,description,…,phase,…``). Ce
module lit ces catalogues et en fabrique un bloc compact injecté dans le contexte
de chaque conversation, pour que Jarvis **connaisse** les workflows BMAD
disponibles (PRD, architecture, sprint planning, stories, review, brainstorming…)
et puisse les prendre en compte quand on le sollicite — typiquement pour cadrer et
piloter le développement d'un repo.

Le bloc donne, par module, le **nom de skill** (`bmad-*`) et son intitulé. Ce nom est
l'argument de `read_skill` du MCP `skills` : le corps complet du workflow (installé
sous `.claude/skills/<nom>/SKILL.md` au build de l'image) est chargé **à la demande**,
seulement quand la conversation en a besoin — pas de bloat, procédure réellement
exécutable. Voir `mcp-servers/skills/catalog.py` (résolution BMAD).

Lecture seule, à la manière du seed skills : les CSV sont lus **en place** depuis
``JARVIS_BMAD_DIR`` (défaut ``/opt/jarvis/seed/_bmad``, où le Dockerfile copie
``_bmad/``), jamais recopiés sur le volume. Pas de dépendance YAML/pandas — csv
stdlib. Import à plat (``from . import bmad``).
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Où vivent les catalogues BMAD dans l'image (cf. Dockerfile COPY _bmad/).
BMAD_DIR = Path(os.getenv("JARVIS_BMAD_DIR", "/opt/jarvis/seed/_bmad"))
# Où vivent les CORPS des workflows (SKILL.md, installés au build). Sert à ne
# proposer que des noms réellement résolvables par read_skill (le CSV de certains
# modules — WDS — liste des alias qui ne correspondent pas aux dossiers installés).
BMAD_SKILLS_DIR = Path(os.getenv("JARVIS_BMAD_SKILLS_DIR", "/opt/jarvis/seed/.claude/skills"))

# Le bloc est injecté partout : on le garde borné.
MAX_BMAD_CHARS = 2600

# Ordre d'affichage stable : le flux de dev (bmm) d'abord, puis les modules
# transverses, puis l'automation. Les modules inconnus suivent, triés.
_MODULE_ORDER = [
    "BMad Method",
    "Web Design Studio",
    "Test Architecture Enterprise",
    "Creative Intelligence Suite",
    "BMad Builder",
    "BMAD Loop Skills",
]


def _help_files() -> list[Path]:
    """Tous les ``module-help.csv`` sous BMAD_DIR (top-level + un par module)."""
    if not BMAD_DIR.is_dir():
        return []
    return sorted(BMAD_DIR.glob("**/module-help.csv"))


def list_catalog() -> dict[str, list[tuple[str, str]]]:
    """Capacités BMAD groupées par module : {module: [(skill-name, display-name)]}.

    ``skill-name`` est le répertoire ``bmad-*`` (colonne ``skill`` du CSV) = l'argument
    de ``read_skill``. Ignore les lignes ``_meta`` et celles sans nom de skill ou sans
    intitulé. Déduplique par nom de skill au sein d'un module (un skill à actions
    multiples — ex. tech-writer avec WD/US/MG/VD/EC — n'apparaît qu'une fois), en
    gardant le premier intitulé rencontré.
    """
    catalog: dict[str, list[tuple[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for path in _help_files():
        try:
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    module = (row.get("module") or "").strip()
                    skill = (row.get("skill") or "").strip()
                    display = (row.get("display-name") or "").strip()
                    if not module or skill == "_meta" or not skill or not display:
                        continue
                    bucket = seen.setdefault(module, set())
                    if skill in bucket:
                        continue
                    bucket.add(skill)
                    catalog.setdefault(module, []).append((skill, display))
        except (OSError, csv.Error) as e:
            logger.warning("bmad: cannot read %s: %s", path, e)
    return catalog


def _ordered_modules(catalog: dict) -> list[str]:
    known = [m for m in _MODULE_ORDER if m in catalog]
    rest = sorted(m for m in catalog if m not in _MODULE_ORDER)
    return known + rest


def _installed_bodies() -> set[str]:
    """Noms de skills dont le corps SKILL.md est réellement installé (résolvables)."""
    if not BMAD_SKILLS_DIR.is_dir():
        return set()
    return {d.name for d in BMAD_SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file()}


def catalog_block() -> str:
    """Bloc Markdown compact du catalogue BMAD ("" si rien à injecter).

    Ne liste que des noms **résolvables par read_skill** dès que des corps sont
    installés (filtre sur les SKILL.md présents) ; en l'absence totale de corps
    (install au build échoué / dev local sans install), replie sur le catalogue
    brut du CSV (pure sensibilisation).
    """
    catalog = list_catalog()
    if not catalog:
        return ""
    installed = _installed_bodies()
    # Noms de skills seuls : compact (injecté partout) et c'est l'argument exact de
    # read_skill — le nom `bmad-…` est auto-descriptif, le corps donne le détail.
    lines = []
    for module in _ordered_modules(catalog):
        entries = catalog[module]
        if installed:
            entries = [(s, d) for s, d in entries if s in installed]
        if not entries:
            continue  # module sans corps résolvable (ex. WDS) — on ne le propose pas
        names = ", ".join(f"`{skill}`" for skill, _ in entries)
        lines.append(f"- **{module}** : {names}")
    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > MAX_BMAD_CHARS:
        body = body[:MAX_BMAD_CHARS].rstrip() + "\n…(catalogue BMAD tronqué)"
    return (
        "## Capacités BMAD (méthodologie de dev)\n"
        + body
        + "\n_Chaque nom `bmad-…` est un workflow BMAD **et** l'argument de `read_skill` "
        "du MCP `skills` : charge le corps complet de la procédure **à la demande** quand "
        "tu en as besoin (ou `attach_skill` pour le garder dans cette conversation). "
        "Utile surtout pour cadrer et piloter le développement d'un repo : product-brief → "
        "PRD → architecture → epics/stories → sprint → dev → review. Mobilise-les dès "
        "qu'une demande porte sur la conception ou la conduite d'un projet logiciel "
        "plutôt que d'improviser._"
    )
