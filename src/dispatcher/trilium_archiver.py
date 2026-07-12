"""Trilium archiver — archives conversations, monitoring, memory and skills.

Uses the Trilium ETAPI to create/update notes. Note structure:
  Jarvis (root note)
  ├── Conversations
  │   └── <channel-name>
  │       └── YYYY-MM-DD — <channel-name>   (one note per day, turns appended)
  ├── Monitoring
  │   └── <check-name>                       (results appended chronologically)
  ├── Mémoire Jarvis
  │   └── <memory-name>                      (replaced on each sync)
  └── Skills
      └── <skill-name>                       (replaced on each sync)

Note IDs are cached in /home/jarvis/memory/trilium-note-ids.json to avoid
repeated search calls.

Content is sent as text/x-markdown — Trilium renders it natively.

Required env vars:
  TRILIUM_URL         — Trilium base URL (e.g. http://trilium.trilium.svc.cluster.local:8080)
  TRILIUM_ETAPI_TOKEN — API token from Trilium Options → ETAPI

Optional:
  TRILIUM_SYNC_INTERVAL   — Memory/skills sync interval in seconds (default: 3600)
  TRILIUM_ARCHIVE_CONV    — Archive user conversations (default: true)
  TRILIUM_ARCHIVE_MONITOR — Archive monitor results (default: true)
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TRILIUM_URL = os.getenv("TRILIUM_URL", "").rstrip("/")
TRILIUM_ETAPI_TOKEN = os.getenv("TRILIUM_ETAPI_TOKEN", "")
ARCHIVE_CONV = os.getenv("TRILIUM_ARCHIVE_CONV", "true").lower() == "true"
ARCHIVE_MONITOR = os.getenv("TRILIUM_ARCHIVE_MONITOR", "true").lower() == "true"
SYNC_INTERVAL = int(os.getenv("TRILIUM_SYNC_INTERVAL", "3600"))

_NOTE_ID_CACHE_PATH = "/home/jarvis/memory/trilium-note-ids.json"
_CONTENT_TYPE = "text/x-markdown"

SECTION_CONVERSATIONS = "Conversations"
SECTION_MONITORING = "Monitoring"
SECTION_MEMORY = "Mémoire Jarvis"
SECTION_SKILLS = "Skills"


def _build_channel_names() -> dict[str, str]:
    """Build channel name mapping from DISCORD_CHANNEL_IDS env var."""
    raw = os.getenv("DISCORD_CHANNEL_IDS", "[]")
    try:
        channels = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("DISCORD_CHANNEL_IDS: invalid JSON, channel names unavailable")
        return {}
    result: dict[str, str] = {}
    for ch in channels:
        cid = str(ch.get("id", "")).strip()
        desc = ch.get("description", "")
        m = re.search(r"(?:repo|l'application)\s+([\w-]+)", desc, re.IGNORECASE)
        if m:
            name = m.group(1)
        else:
            words = re.findall(r"[\w]+", desc.lower())[:2]
            name = "-".join(words) if words else f"channel-{cid}"
        result[f"discord:channel:{cid}"] = name
    return result


CHANNEL_NAMES: dict[str, str] = _build_channel_names()


class TriliumArchiver:
    """Archives Jarvis data (conversations, monitoring, memory, skills) to Trilium Notes."""

    def __init__(self) -> None:
        self.enabled = bool(TRILIUM_URL and TRILIUM_ETAPI_TOKEN)
        self._cache: dict[str, str] = {}
        if self.enabled:
            self._load_cache()

    # --- Cache ---

    def _load_cache(self) -> None:
        try:
            with open(_NOTE_ID_CACHE_PATH) as f:
                self._cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._cache = {}

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(_NOTE_ID_CACHE_PATH), exist_ok=True)
            with open(_NOTE_ID_CACHE_PATH, "w") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.debug("trilium cache save error: %s", e)

    # --- HTTP client ---

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=TRILIUM_URL + "/etapi",
            headers={"Authorization": f"Bearer {TRILIUM_ETAPI_TOKEN}"},
            timeout=30,
        )

    # --- Note helpers ---

    def _note_exists(self, note_id: str) -> bool:
        try:
            with self._client() as c:
                return c.get(f"/notes/{note_id}").status_code == 200
        except Exception:
            return False

    def _get_or_create(
        self, parent_id: str, title: str, cache_key: Optional[str] = None
    ) -> Optional[str]:
        """Find note by title under parent, or create it. Returns noteId."""
        if cache_key and cache_key in self._cache:
            cached = self._cache[cache_key]
            if self._note_exists(cached):
                return cached
            del self._cache[cache_key]

        try:
            with self._client() as c:
                r = c.get("/notes", params={
                    "search": f"note.title='{title}'",
                    "ancestorNoteId": parent_id,
                    "fastSearch": "false",
                    "limit": "5",
                })
                if r.status_code == 200:
                    results = r.json()
                    if results:
                        note_id = results[0]["noteId"]
                        if cache_key:
                            self._cache[cache_key] = note_id
                            self._save_cache()
                        return note_id

                r2 = c.post("/create-note", json={
                    "parentNoteId": parent_id,
                    "title": title,
                    "type": "text",
                    "content": "",
                    "contentType": _CONTENT_TYPE,
                })
                r2.raise_for_status()
                note_id = r2.json()["note"]["noteId"]
                if cache_key:
                    self._cache[cache_key] = note_id
                    self._save_cache()
                return note_id
        except Exception as e:
            logger.warning("trilium _get_or_create('%s'): %s", title, e)
            return None

    def _jarvis_root(self) -> Optional[str]:
        return self._get_or_create("root", "Jarvis", cache_key="root_jarvis")

    def _section(self, name: str) -> Optional[str]:
        root = self._jarvis_root()
        if not root:
            return None
        return self._get_or_create(root, name, cache_key=f"section_{name}")

    def _append(self, note_id: str, content: str) -> None:
        try:
            with self._client() as c:
                r = c.get(f"/notes/{note_id}/content")
                current = r.text if r.status_code == 200 else ""
                c.put(
                    f"/notes/{note_id}/content",
                    content=(current + content).encode("utf-8"),
                    headers={"Content-Type": _CONTENT_TYPE},
                ).raise_for_status()
        except Exception as e:
            logger.debug("trilium append to %s: %s", note_id, e)

    def _replace(self, note_id: str, content: str) -> None:
        try:
            with self._client() as c:
                c.put(
                    f"/notes/{note_id}/content",
                    content=content.encode("utf-8"),
                    headers={"Content-Type": _CONTENT_TYPE},
                ).raise_for_status()
        except Exception as e:
            logger.debug("trilium replace %s: %s", note_id, e)

    # --- Public API (same interface as DocmostArchiver) ---

    def archive_conversation_turn(
        self,
        conv_key: str,
        role: str,
        content: str,
        ts: Optional[datetime] = None,
    ) -> None:
        if not self.enabled or not ARCHIVE_CONV:
            return
        ts = ts or datetime.now(timezone.utc)
        date_str = ts.strftime("%Y-%m-%d")
        time_str = ts.strftime("%H:%M:%S")

        section_id = self._section(SECTION_CONVERSATIONS)
        if not section_id:
            return

        friendly = CHANNEL_NAMES.get(conv_key, conv_key)
        channel_id = self._get_or_create(
            section_id, friendly, cache_key=f"conv_channel_{conv_key}"
        )
        if not channel_id:
            return

        day_title = f"{date_str} — {friendly}"
        day_id = self._get_or_create(
            channel_id, day_title, cache_key=f"conv_day_{conv_key}_{date_str}"
        )
        if not day_id:
            return

        md = f"**[{time_str}] {role.upper()}**\n\n{content}\n\n---\n\n"
        self._append(day_id, md)

    def archive_monitor_result(
        self,
        check_name: str,
        content: str,
        ts: Optional[datetime] = None,
    ) -> None:
        if not self.enabled or not ARCHIVE_MONITOR:
            return
        ts = ts or datetime.now(timezone.utc)
        time_str = ts.strftime("%Y-%m-%d %H:%M UTC")

        section_id = self._section(SECTION_MONITORING)
        if not section_id:
            return

        check_id = self._get_or_create(
            section_id, check_name, cache_key=f"monitor_{check_name}"
        )
        if not check_id:
            return

        md = f"## {time_str}\n\n{content}\n\n---\n\n"
        self._append(check_id, md)

    def sync_memory(self, memory_dir: str) -> None:
        if not self.enabled:
            return
        section_id = self._section(SECTION_MEMORY)
        if not section_id:
            return

        for path in Path(memory_dir).rglob("*.md"):
            relative = path.relative_to(memory_dir)
            parts = list(relative.with_suffix("").parts)
            try:
                content = path.read_text(encoding="utf-8")
                parent_id = section_id
                for part in parts[:-1]:
                    parent_id = self._get_or_create(
                        parent_id, part, cache_key=f"mem_dir_{part}"
                    ) or section_id
                leaf_id = self._get_or_create(
                    parent_id, parts[-1],
                    cache_key=f"mem_{'_'.join(parts)}"
                )
                if leaf_id:
                    self._replace(leaf_id, content)
            except Exception as e:
                logger.debug("sync_memory %s: %s", "/".join(parts), e)

    def sync_skills(self, skills_dir: str) -> None:
        if not self.enabled:
            return
        section_id = self._section(SECTION_SKILLS)
        if not section_id:
            return

        for path in Path(skills_dir).rglob("SKILL.md"):
            skill_name = path.parent.name
            try:
                content = path.read_text(encoding="utf-8")
                note_id = self._get_or_create(
                    section_id, skill_name, cache_key=f"skill_{skill_name}"
                )
                if note_id:
                    self._replace(note_id, content)
            except Exception as e:
                logger.debug("sync_skills %s: %s", skill_name, e)
