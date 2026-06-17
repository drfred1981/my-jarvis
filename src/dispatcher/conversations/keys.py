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

from dataclasses import dataclass

SEP = ":"

# Channels whose conversations represent genuine human activity.
USER_CHANNELS = frozenset({"discord", "web", "synology"})

# Singleton key for the autonomous introspection track (Track B).
INTROSPECTION = "introspection"


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
