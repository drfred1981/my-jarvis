"""Durable, file-backed registry of conversations.

Maps a conversation key (see `keys`) to its Claude Code session id and activity
metadata, persisted as JSON. This replaces the in-memory session dict so that
`--resume` continuity and idle/activity tracking survive process restarts.

The registry is intentionally free of metrics / framework coupling: it is a
plain data store. Callers (e.g. `ClaudeRunner`) own observability.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from . import keys

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Conversation:
    """One conversational context and its durable state."""
    key: str
    claude_session_id: str | None = None
    channel: str = ""
    mode: str = "direct"                 # direct | multiuser
    participants: list[str] = field(default_factory=list)
    created_at: str = ""
    last_activity: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in fields})


class ConversationRegistry:
    """Thread-safe store of conversations backed by a single JSON file."""

    def __init__(self, index_path: str):
        self._path = index_path
        self._lock = threading.RLock()
        self._items: dict[str, Conversation] = {}
        self._load()

    # --- persistence ---

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path) as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("ConversationRegistry: cannot load %s: %s", self._path, e)
            return
        for key, d in raw.get("conversations", {}).items():
            try:
                self._items[key] = Conversation.from_dict({**d, "key": key})
            except TypeError:
                logger.warning("ConversationRegistry: skipping malformed entry %r", key)
        logger.info("ConversationRegistry: loaded %d conversations from %s",
                    len(self._items), self._path)

    def _save_locked(self) -> None:
        """Atomic write (tmp file + os.replace). Caller must hold the lock."""
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        data = {"conversations": {k: c.to_dict() for k, c in self._items.items()}}
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._path)
        except OSError as e:
            logger.error("ConversationRegistry: save failed: %s", e)
            if os.path.exists(tmp):
                os.unlink(tmp)

    # --- API ---

    def get(self, key: str) -> Conversation | None:
        with self._lock:
            return self._items.get(key)

    def get_or_create(self, key: str, *, channel: str | None = None,
                      mode: str = "direct", participants=None) -> Conversation:
        with self._lock:
            conv = self._items.get(key)
            if conv is None:
                now = _now().isoformat()
                conv = Conversation(
                    key=key,
                    channel=channel or keys.parse(key).channel,
                    mode=mode,
                    participants=list(participants or []),
                    created_at=now,
                    last_activity=now,
                )
                self._items[key] = conv
                self._save_locked()
            return conv

    def touch(self, key: str, when: datetime | None = None) -> None:
        """Mark activity on a conversation (no-op if unknown)."""
        with self._lock:
            conv = self._items.get(key)
            if conv is None:
                return
            conv.last_activity = (when or _now()).isoformat()
            self._save_locked()

    def record_session_id(self, key: str, claude_session_id: str) -> None:
        with self._lock:
            conv = self._items.get(key)
            if conv is None or conv.claude_session_id == claude_session_id:
                return
            conv.claude_session_id = claude_session_id
            self._save_locked()

    def set_mode(self, key: str, mode: str) -> None:
        """Update a conversation's mode ('direct' | 'multiuser') if it changed."""
        with self._lock:
            conv = self._items.get(key)
            if conv and conv.mode != mode:
                conv.mode = mode
                self._save_locked()

    def reset_session(self, key: str) -> None:
        """Forget the Claude session id but keep the conversation entry."""
        with self._lock:
            conv = self._items.get(key)
            if conv and conv.claude_session_id is not None:
                conv.claude_session_id = None
                self._save_locked()

    def clear(self, key: str) -> bool:
        """Drop a conversation entirely. Returns True if it existed."""
        with self._lock:
            if key in self._items:
                del self._items[key]
                self._save_locked()
                return True
            return False

    def list(self) -> list[Conversation]:
        with self._lock:
            return list(self._items.values())

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def last_user_activity(self) -> datetime | None:
        """Most recent activity across real *user* conversations only
        (excludes introspection / monitor tracks). Feeds the idle backoff timer.
        """
        latest: datetime | None = None
        with self._lock:
            for conv in self._items.values():
                if not keys.is_user(conv.key) or not conv.last_activity:
                    continue
                try:
                    ts = datetime.fromisoformat(conv.last_activity)
                except ValueError:
                    continue
                if latest is None or ts > latest:
                    latest = ts
        return latest
