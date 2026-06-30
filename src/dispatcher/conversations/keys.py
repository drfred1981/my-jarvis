"""Conversation key construction and parsing.

A conversation key is a stable, structured identifier for one conversational
context: a Discord DM, a guild channel, a thread, a web session, the autonomous
introspection track, or an infra monitor check.

Format — colon-separated segments:

    discord:dm:<user_id>        discord:channel:<id>      discord:thread:<id>
    web:<session>               synology:<user_id>
    introspection               monitor:<check-name>

Only the `discord` / `web` / `synology` channels represent real human activity;
`introspection` and `monitor:*` are system tracks and are excluded from
user-activity aggregation (see `registry.last_user_activity`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

SEP = ":"

# Channels whose conversations represent genuine human activity.
USER_CHANNELS = frozenset({"discord", "web", "synology"})

# Singleton key for the autonomous introspection track (Track B).
INTROSPECTION = "introspection"

# Fixed namespace for deriving deterministic Claude session ids from a key.
# Stable across deploys/pods → uuid5(NS, key) reconstructs the same session id
# without any stored state, so a lost session transcript self-heals (see
# `keys.session_id`). Do NOT change this value: it would orphan every session.
_SESSION_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


# --- builders ---

def discord_dm(user_id) -> str:
    return SEP.join(("discord", "dm", str(user_id)))


def discord_channel(channel_id) -> str:
    return SEP.join(("discord", "channel", str(channel_id)))


def discord_thread(thread_id) -> str:
    return SEP.join(("discord", "thread", str(thread_id)))


def web(session) -> str:
    return SEP.join(("web", str(session)))


def synology(user_id) -> str:
    return SEP.join(("synology", str(user_id)))


def monitor(check) -> str:
    return SEP.join(("monitor", str(check)))


# --- parsing ---

@dataclass(frozen=True)
class ParsedKey:
    channel: str   # discord | web | synology | introspection | monitor | <unknown>
    kind: str      # dm | channel | thread | "" (for non-discord)
    ident: str     # trailing identifier ("" for introspection)

    @property
    def is_user(self) -> bool:
        return self.channel in USER_CHANNELS


def parse(key: str) -> ParsedKey:
    parts = key.split(SEP)
    channel = parts[0]
    if channel == "discord" and len(parts) >= 3:
        return ParsedKey("discord", parts[1], SEP.join(parts[2:]))
    if channel in ("web", "synology", "monitor") and len(parts) >= 2:
        return ParsedKey(channel, "", SEP.join(parts[1:]))
    # introspection, or any single-segment / unrecognized key
    return ParsedKey(channel, "", SEP.join(parts[1:]) if len(parts) > 1 else "")


def is_user(key: str) -> bool:
    """True if this key is a real user conversation (not a system track)."""
    return parse(key).is_user


# --- derived technical handles (pure functions of the global id) ---

def slug(key: str) -> str:
    """Slug-safe form of a key (':' → '-'), used for file/context names."""
    return key.replace(SEP, "-")


def context_name(key: str) -> str:
    """Memory context name holding a conversation's distilled local context.

    Canonical resolver: both the context injector and the skills reader agree on
    this (e.g. ``discord:dm:1`` → ``conversations/discord-dm-1``).
    """
    return "conversations/" + slug(key)


def session_id(key: str) -> str:
    """Deterministic Claude session id (uuid5) for a conversation key.

    A pure function of the global conversation id → reproducible without any
    stored state. Combined with ``claude --session-id`` (idempotent: resumes if
    the transcript exists, else creates it), this removes the stale-``--resume``
    failure mode entirely.
    """
    return str(uuid.uuid5(_SESSION_NS, key))
