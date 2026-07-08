"""Docmost archiver — archives conversations, monitoring, memory and skills.

Uses TipTap/ProseMirror JSON (format=json) for all content operations.
Content is converted from markdown server-side via a built-in converter.

Required env vars:
  DOCMOST_URL       — Docmost base URL
  DOCMOST_API_KEY   — API key Bearer auth (preferred)
  DOCMOST_USER      — Email for cookie auth (fallback)
  DOCMOST_PASSWORD  — Password for cookie auth (fallback)

Optional:
  DOCMOST_SPACE_ID          — Target space (auto-discovers "General" if absent)
  DOCMOST_ARCHIVE_CONV      — Archive user conversations (default: true)
  DOCMOST_ARCHIVE_MONITOR   — Archive monitor results (default: true)
  DOCMOST_SYNC_INTERVAL     — Memory/skills sync interval in seconds (default: 3600)
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DOCMOST_URL = os.getenv("DOCMOST_URL", "").rstrip("/")
DOCMOST_API_KEY = os.getenv("DOCMOST_API_KEY", "")
DOCMOST_USER = os.getenv("DOCMOST_USER", "")
DOCMOST_PASSWORD = os.getenv("DOCMOST_PASSWORD", "")
DOCMOST_SPACE_ID = os.getenv("DOCMOST_SPACE_ID", "")
ARCHIVE_CONV = os.getenv("DOCMOST_ARCHIVE_CONV", "true").lower() == "true"
ARCHIVE_MONITOR = os.getenv("DOCMOST_ARCHIVE_MONITOR", "true").lower() == "true"
SYNC_INTERVAL = int(os.getenv("DOCMOST_SYNC_INTERVAL", "3600"))

SECTION_CONVERSATIONS = "Conversations"
SECTION_MONITORING = "Monitoring"
SECTION_MEMORY = "Mémoire Jarvis"
SECTION_SKILLS = "Skills"

def _build_channel_names() -> dict[str, str]:
    """Build channel name mapping from DISCORD_CHANNEL_IDS env var.

    Each entry has {id, description}. Name is extracted from description:
    - "Pilotage du repo <name>" or "l'application <name>" → <name>
    - Otherwise: first two words joined with '-'
    """
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


# ---------------------------------------------------------------------------
# Markdown → TipTap/ProseMirror JSON converter
# ---------------------------------------------------------------------------

def _pid() -> str:
    return uuid.uuid4().hex[:12]


_INLINE_RE = re.compile(
    r"(\*\*|__)(?P<bold>.+?)(\*\*|__)"
    r"|(\*|_)(?P<italic>.+?)(\*|_)"
    r"|~~(?P<strike>.+?)~~"
    r"|`(?P<code>[^`]+?)`"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<link_href>[^)]+)\)"
    r"|(?P<text>[^*_~`\[]+)"
)


def _parse_inline(text: str) -> list:
    nodes = []
    for m in _INLINE_RE.finditer(text):
        if m.group("bold"):
            nodes.append({"type": "text", "text": m.group("bold"),
                          "marks": [{"type": "bold"}]})
        elif m.group("italic"):
            nodes.append({"type": "text", "text": m.group("italic"),
                          "marks": [{"type": "italic"}]})
        elif m.group("strike"):
            nodes.append({"type": "text", "text": m.group("strike"),
                          "marks": [{"type": "strike"}]})
        elif m.group("code"):
            nodes.append({"type": "text", "text": m.group("code"),
                          "marks": [{"type": "code"}]})
        elif m.group("link_text"):
            nodes.append({"type": "text", "text": m.group("link_text"),
                          "marks": [{"type": "link", "attrs": {
                              "href": m.group("link_href"), "target": "_blank"
                          }}]})
        elif m.group("text"):
            nodes.append({"type": "text", "text": m.group("text")})
    return [n for n in nodes if n.get("text")]


def _para(text: str) -> dict:
    return {"type": "paragraph", "attrs": {"id": _pid(), "textAlign": None},
            "content": _parse_inline(text) or [{"type": "text", "text": ""}]}


def _heading(level: int, text: str) -> dict:
    return {"type": "heading",
            "attrs": {"id": _pid(), "level": level,
                      "textAlign": None, "textColor": None},
            "content": _parse_inline(text)}


def _list_item(text: str) -> dict:
    return {"type": "listItem", "attrs": {"id": _pid()},
            "content": [_para(text)]}


def md_to_tiptap(text: str) -> dict:
    """Convert a Markdown string to a TipTap doc dict.

    Handles: headings, paragraphs, bold/italic/code/strike/link inline,
    bullet lists, ordered lists, code blocks, horizontal rules, blockquotes.
    """
    nodes: list = []
    in_code = False
    code_lang = ""
    code_lines: list = []
    bullet_items: list = []
    ordered_items: list = []
    quote_lines: list = []

    def flush_bullet():
        if bullet_items:
            nodes.append({"type": "bulletList",
                           "content": [_list_item(i) for i in bullet_items]})
            bullet_items.clear()

    def flush_ordered():
        if ordered_items:
            nodes.append({"type": "orderedList", "attrs": {"start": 1},
                           "content": [_list_item(i) for i in ordered_items]})
            ordered_items.clear()

    def flush_quote():
        if quote_lines:
            inner = md_to_tiptap("\n".join(quote_lines))
            nodes.append({"type": "blockquote", "content": inner["content"]})
            quote_lines.clear()

    def flush_all():
        flush_bullet(); flush_ordered(); flush_quote()

    for line in text.split("\n"):
        # code fence
        if line.startswith("```"):
            if in_code:
                flush_all()
                nodes.append({"type": "codeBlock",
                               "attrs": {"id": _pid(), "language": code_lang or None},
                               "content": [{"type": "text", "text": "\n".join(code_lines)}]
                               if code_lines else []})
                code_lines.clear(); code_lang = ""; in_code = False
            else:
                flush_all(); code_lang = line[3:].strip(); in_code = True
            continue
        if in_code:
            code_lines.append(line); continue
        # horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line.strip()):
            flush_all()
            nodes.append({"type": "horizontalRule", "attrs": {"id": _pid()}}); continue
        # heading
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_all()
            lvl = min(len(m.group(1)), 6); txt = m.group(2).strip()
            if txt: nodes.append(_heading(lvl, txt))
            continue
        # blockquote
        m = re.match(r"^>\s?(.*)", line)
        if m:
            flush_bullet(); flush_ordered(); quote_lines.append(m.group(1)); continue
        elif quote_lines:
            flush_quote()
        # ordered list
        m = re.match(r"^\d+\.\s+(.*)", line)
        if m:
            flush_bullet(); flush_quote(); ordered_items.append(m.group(1)); continue
        elif ordered_items and not line.strip():
            flush_ordered()
        # bullet list
        m = re.match(r"^[*\-]\s+(.*)", line)
        if m:
            flush_ordered(); flush_quote(); bullet_items.append(m.group(1)); continue
        elif bullet_items and not line.strip():
            flush_bullet()
        # empty
        if not line.strip():
            flush_all(); continue
        # paragraph
        flush_all(); nodes.append(_para(line))

    flush_all()
    if in_code and code_lines:
        nodes.append({"type": "codeBlock",
                       "attrs": {"id": _pid(), "language": code_lang or None},
                       "content": [{"type": "text", "text": "\n".join(code_lines)}]})
    if not nodes:
        nodes.append(_para(""))
    return {"type": "doc", "content": nodes}


# ---------------------------------------------------------------------------
# DocmostArchiver
# ---------------------------------------------------------------------------

class DocmostArchiver:
    """Archives Jarvis data to Docmost using TipTap JSON (format=json)."""

    def __init__(self):
        self._enabled = bool(
            DOCMOST_URL and (DOCMOST_API_KEY or (DOCMOST_USER and DOCMOST_PASSWORD))
        )
        self._space_id: str = DOCMOST_SPACE_ID
        self._page_cache: dict[str, str] = {}
        self._session_cookies: dict = {}
        if self._enabled:
            logger.info("DocmostArchiver enabled (url=%s)", DOCMOST_URL)
        else:
            logger.info("DocmostArchiver disabled")

    @property
    def enabled(self) -> bool:
        return self._enabled

    # --- HTTP ---

    def _make_client(self) -> httpx.Client:
        if DOCMOST_API_KEY:
            return httpx.Client(base_url=DOCMOST_URL,
                                headers={"Authorization": f"Bearer {DOCMOST_API_KEY}"},
                                timeout=30)
        if not self._session_cookies:
            with httpx.Client(base_url=DOCMOST_URL, timeout=30) as c:
                r = c.post("/api/auth/login",
                           json={"email": DOCMOST_USER, "password": DOCMOST_PASSWORD})
                r.raise_for_status()
                self._session_cookies = dict(r.cookies)
        return httpx.Client(base_url=DOCMOST_URL, cookies=self._session_cookies, timeout=30)

    def _post(self, path: str, body: dict) -> dict:
        try:
            with self._make_client() as c:
                r = c.post(path, json=body)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._session_cookies = {}
            logger.debug("Docmost %s error: %s", path, e)
            return {}
        except Exception as e:
            logger.debug("Docmost %s error: %s", path, e)
            return {}

    # --- Space ---

    def _ensure_space(self) -> str:
        if self._space_id:
            return self._space_id
        data = self._post("/api/spaces/", {"limit": 20, "page": 1})
        items = data.get("data", {}).get("items", [])
        for item in items:
            if item.get("name") == "General":
                self._space_id = item["id"]
                return self._space_id
        if items:
            self._space_id = items[0]["id"]
        return self._space_id

    # --- Page tree ---

    def _list_children(self, space_id: str,
                        parent_id: Optional[str] = None) -> list:
        body = {"spaceId": space_id, "limit": 100, "page": 1}
        if parent_id:
            body["pageId"] = parent_id
        data = self._post("/api/pages/sidebar-pages", body)
        items = data.get("data", {})
        if isinstance(items, dict):
            items = items.get("items", [])
        return items if isinstance(items, list) else []

    def _find_child(self, space_id: str, title: str,
                    parent_id: Optional[str] = None) -> Optional[str]:
        cache_key = f"{space_id}/{parent_id or 'root'}/{title}"
        if cache_key in self._page_cache:
            return self._page_cache[cache_key]
        for page in self._list_children(space_id, parent_id):
            if page.get("title") == title:
                pid = page["id"]
                self._page_cache[cache_key] = pid
                return pid
        return None

    def _create_page(self, space_id: str, title: str,
                     content_md: str = "",
                     parent_id: Optional[str] = None) -> Optional[str]:
        body: dict = {"spaceId": space_id, "title": title}
        if content_md:
            body["content"] = md_to_tiptap(content_md)
            body["format"] = "json"
        if parent_id:
            body["parentPageId"] = parent_id
        data = self._post("/api/pages/create", body)
        page = data.get("data", data)
        if isinstance(page, dict):
            pid = page.get("id")
            if pid:
                cache_key = f"{space_id}/{parent_id or 'root'}/{title}"
                self._page_cache[cache_key] = pid
                return pid
        return None

    def _find_or_create(self, space_id: str, title: str,
                         content_md: str = "",
                         parent_id: Optional[str] = None) -> Optional[str]:
        found = self._find_child(space_id, title, parent_id)
        return found if found else self._create_page(space_id, title, content_md, parent_id)

    def _update(self, page_id: str, content_md: str) -> None:
        self._post("/api/pages/update", {
            "pageId": page_id,
            "content": md_to_tiptap(content_md),
            "format": "json",
            "operation": "replace",
        })

    def _append(self, page_id: str, content_md: str) -> None:
        self._post("/api/pages/update", {
            "pageId": page_id,
            "content": md_to_tiptap(content_md),
            "format": "json",
            "operation": "append",
        })

    def _ensure_section(self, space_id: str, name: str,
                         parent_id: Optional[str] = None) -> Optional[str]:
        return self._find_or_create(
            space_id, name,
            content_md=f"# {name}\n\nArchive Jarvis.",
            parent_id=parent_id,
        )

    # --- Public API ---

    def _display_name(self, conv_key: str) -> str:
        return CHANNEL_NAMES.get(conv_key, conv_key)

    def archive_conversation_turn(self, conv_key: str,
                                  message: str, response: str) -> None:
        """Append one conversation turn under Conversations/<name>/<YYYY-MM-DD>."""
        if not self._enabled or not ARCHIVE_CONV:
            return
        ts = datetime.now(timezone.utc)
        try:
            space_id = self._ensure_space()
            if not space_id:
                return
            section_id = self._ensure_section(space_id, SECTION_CONVERSATIONS)
            name = self._display_name(conv_key)
            conv_id = self._find_or_create(
                space_id, name,
                content_md=f"# Conversations — {name}\n\nArchive du canal `{conv_key}`.",
                parent_id=section_id,
            )
            date_str = ts.strftime("%Y-%m-%d")
            page_id = self._find_or_create(
                space_id, date_str,
                content_md=f"# {name} — {date_str}\n\n",
                parent_id=conv_id,
            )
            if page_id:
                hhmm = ts.strftime("%H:%M")
                msg_preview = message[:300].replace("\n", " ")
                block = (
                    f"## {hhmm} UTC\n\n"
                    f"**→** {msg_preview}\n\n"
                    f"{response[:2000]}\n\n"
                    "---"
                )
                self._append(page_id, block)
        except Exception as e:
            logger.debug("archive_conversation_turn error: %s", e)

    def archive_monitor_result(self, check_name: str, response: str) -> None:
        """Append one monitor result under Monitoring/<check_name>/<YYYY-MM-DD>."""
        if not self._enabled or not ARCHIVE_MONITOR:
            return
        ts = datetime.now(timezone.utc)
        try:
            space_id = self._ensure_space()
            if not space_id:
                return
            section_id = self._ensure_section(space_id, SECTION_MONITORING)
            check_id = self._find_or_create(
                space_id, check_name,
                content_md=f"# Monitoring — {check_name}\n\nHistorique des checks `{check_name}`.",
                parent_id=section_id,
            )
            date_str = ts.strftime("%Y-%m-%d")
            page_id = self._find_or_create(
                space_id, date_str,
                content_md=f"# {check_name} — {date_str}\n\n",
                parent_id=check_id,
            )
            if page_id:
                hhmm = ts.strftime("%H:%M")
                block = f"## {hhmm} UTC\n\n{response[:3000]}\n\n---"
                self._append(page_id, block)
        except Exception as e:
            logger.debug("archive_monitor_result error: %s", e)

    def sync_memory(self, memory_dir: str) -> None:
        """Upsert all *.md files from memory_dir under Mémoire Jarvis/."""
        if not self._enabled:
            return
        ts_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            space_id = self._ensure_space()
            if not space_id:
                return
            section_id = self._ensure_section(space_id, SECTION_MEMORY)
            for root, _dirs, files in os.walk(memory_dir):
                for fname in sorted(files):
                    if not fname.endswith(".md"):
                        continue
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, memory_dir).replace("\\", "/")
                    title = rel.removesuffix(".md")
                    # Friendly name for known channels
                    if title.startswith("conversations/"):
                        key = title.replace("conversations/", "")
                        # convert file slug → conv_key
                        conv_key = "discord:" + key.replace("-", ":channel:", 1)
                        friendly = CHANNEL_NAMES.get(conv_key, key)
                        title = f"conversations/{friendly}"
                    try:
                        with open(fpath, encoding="utf-8") as f:
                            raw = f.read()
                    except OSError:
                        continue
                    content_md = f"_Sync : {ts_label}_\n\n---\n\n{raw}"
                    page_id = self._find_or_create(
                        space_id, title, content_md=content_md, parent_id=section_id
                    )
                    if page_id:
                        self._update(page_id, content_md)
        except Exception as e:
            logger.debug("sync_memory error: %s", e)

    def sync_skills(self, skills_dir: str) -> None:
        """Upsert all SKILL.md files under Skills/."""
        if not self._enabled or not os.path.isdir(skills_dir):
            return
        ts_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            space_id = self._ensure_space()
            if not space_id:
                return
            section_id = self._ensure_section(space_id, SECTION_SKILLS)
            for skill_name in sorted(os.listdir(skills_dir)):
                skill_file = os.path.join(skills_dir, skill_name, "SKILL.md")
                if not os.path.isfile(skill_file):
                    continue
                try:
                    with open(skill_file, encoding="utf-8") as f:
                        raw = f.read()
                except OSError:
                    continue
                content_md = f"_Sync : {ts_label}_\n\n---\n\n{raw}"
                page_id = self._find_or_create(
                    space_id, skill_name, content_md=content_md, parent_id=section_id
                )
                if page_id:
                    self._update(page_id, content_md)
        except Exception as e:
            logger.debug("sync_skills error: %s", e)
