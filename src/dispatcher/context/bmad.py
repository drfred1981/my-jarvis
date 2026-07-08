"""BMAD capability catalog, for context injection.

Jarvis pilote des repos avec la méthode BMAD (BMad Method + modules) installée
sous ``_bmad/``. Chaque module y déclare ses capacités dans un ``module-help.csv``
(colonnes : ``module,skill,display-name,menu-code,description,…,phase,…``). Ce
module lit ces catalogues et en fabrique un bloc compact injecté dans le contexte
de chaque conversation, pour que Jarvis **connaisse** les workflows BMAD
disponibles (PRD, architecture, sprint planning, stories, review, brainstorming…)
et puisse les prendre en compte quand on le sollicite — typiquement pour cadrer et
piloter le développement d'un repo.

C'est un catalogue de *sensibilisation* : les corps des procédures BMAD ne sont pas
tous présents dans l'image (ils vivent en amont, dans l'outillage BMAD). Le bloc
donne donc le nom, le code menu et une intention — pas la procédure exécutable.

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
    """Capacités BMAD groupées par module : {module: [(menu-code, display-name)]}.

    Ignore les lignes ``_meta`` et celles sans nom affichable. Déduplique par
    (code, nom) au sein d'un module pour ne pas répéter un skill à actions
    multiples (ex. un même skill exposé sous plusieurs codes menu).
    """
    catalog: dict[str, list[tuple[str, str]]] = {}
    seen: dict[str, set[tuple[str, str]]] = {}
    for path in _help_files():
        try:
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    module = (row.get("module") or "").strip()
                    skill = (row.get("skill") or "").strip()
                    display = (row.get("display-name") or "").strip()
                    code = (row.get("menu-code") or "").strip()
                    if not module or skill == "_meta" or not display:
                        continue
                    entry = (code, display)
                    bucket = seen.setdefault(module, set())
                    if entry in bucket:
                        continue
                    bucket.add(entry)
                    catalog.setdefault(module, []).append(entry)
        except (OSError, csv.Error) as e:
            logger.warning("bmad: cannot read %s: %s", path, e)
    return catalog


def _ordered_modules(catalog: dict) -> list[str]:
    known = [m for m in _MODULE_ORDER if m in catalog]
    rest = sorted(m for m in catalog if m not in _MODULE_ORDER)
    return known + rest


def catalog_block() -> str:
    """Bloc Markdown compact du catalogue BMAD ("" si rien à injecter)."""
    catalog = list_catalog()
    if not catalog:
        return ""
    lines = []
    for module in _ordered_modules(catalog):
        entries = catalog[module]
        rendered = " · ".join(
            f"{name} (`{code}`)" if code else name for code, name in entries
        )
        lines.append(f"- **{module}** : {rendered}")
    body = "\n".join(lines)
    if len(body) > MAX_BMAD_CHARS:
        body = body[:MAX_BMAD_CHARS].rstrip() + "\n…(catalogue BMAD tronqué)"
    return (
        "## Capacités BMAD (méthodologie de dev, catalogue)\n"
        + body
        + "\n_Workflows BMAD installés sous `_bmad/` (codes menu entre backticks). "
        "Utile surtout pour cadrer et piloter le développement d'un repo (PRD → "
        "architecture → epics/stories → sprint → dev → review). Ce sont des "
        "capacités de méthode : mobilise-les quand la demande porte sur la "
        "conception ou la conduite d'un projet logiciel._"
    )
