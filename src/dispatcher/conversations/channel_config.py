"""Parse the `DISCORD_CHANNEL_IDS` configuration.

Two accepted formats (auto-detected), so existing deployments keep working:

  - **structured** (recommended) — a JSON array of objects, each with a required
    ``id`` and an optional ``description`` that seeds the conversation's minimal
    context (mirrors the ``GIT_REPOS`` alias+description convention)::

        DISCORD_CHANNEL_IDS=[
          {"id": "123", "description": "Pilotage du dev de my-jarvis"},
          {"id": "456", "description": "Home Assistant / automations"}
        ]

  - **legacy** — a comma-separated list of channel ids (no descriptions)::

        DISCORD_CHANNEL_IDS=123,456

The list of objects (rather than ``{id: description}``) keeps the schema
extensible: a new optional field can be added later without breaking configs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelConfig:
    id: str
    description: str = ""


def parse_channels(raw: str | None) -> list[ChannelConfig]:
    """Parse the env value into a list of ChannelConfig (empty list if unset).

    Invalid JSON or malformed entries are logged and skipped, never raised, so a
    config typo degrades gracefully instead of taking the bot down.
    """
    if not raw or not raw.strip():
        return []
    text = raw.strip()

    # Structured JSON form.
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("DISCORD_CHANNEL_IDS: invalid JSON, ignoring (%s)", e)
            return []
        if isinstance(data, dict):           # tolerate {"id": "desc", ...}
            data = [{"id": k, "description": v} for k, v in data.items()]
        out: list[ChannelConfig] = []
        for entry in data if isinstance(data, list) else []:
            if isinstance(entry, str):
                out.append(ChannelConfig(id=entry.strip()))
            elif isinstance(entry, dict) and str(entry.get("id", "")).strip():
                out.append(ChannelConfig(
                    id=str(entry["id"]).strip(),
                    description=str(entry.get("description", "")).strip(),
                ))
            else:
                logger.warning("DISCORD_CHANNEL_IDS: skipping malformed entry %r", entry)
        return out

    # Legacy comma-separated form.
    return [ChannelConfig(id=part.strip()) for part in text.split(",") if part.strip()]


def channel_ids(raw: str | None) -> set[int]:
    """The set of integer channel ids (for the allowed-channels gate)."""
    ids: set[int] = set()
    for cfg in parse_channels(raw):
        try:
            ids.add(int(cfg.id))
        except ValueError:
            logger.warning("DISCORD_CHANNEL_IDS: non-numeric id %r ignored", cfg.id)
    return ids
