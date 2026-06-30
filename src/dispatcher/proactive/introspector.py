"""Track B — autonomous introspection with deterministic exponential backoff.

Owns the *cadence* of proactive introspection (the code, not the prompt):

  - firm floor of 15 min; the interval doubles each idle cycle up to a 5h cap;
  - any chat activity resets the interval to the floor and wakes the loop early;
  - fully suppressed during quiet hours (night mode, see `quiet`);
  - depth chosen by idle duration: light (≤20 min) / medium (≤80 min) / deep (>80 min).

When users are actively chatting, introspection is skipped entirely (stay reactive,
don't burn tokens). The "worth saying?" judgment and content live in `prompts`.

Coaching delivery (per-conversation isolation doctrine):
  - *team review* : every cycle that surfaces something updates `global/state` and is
                    posted ONLY to the dedicated coaching channel (`notify_coaching`),
                    never broadcast into conversation-specific channels.
  - *per-conversation* : deep cycles only → for each recently-active user conversation,
                    run a coaching prompt inside THAT conversation's own local context
                    and post the tailored result back INTO that conversation
                    (`notifier.notify_conversation`), so suggestions are about that
                    conversation's own subject/repo — not generic.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from conversations import keys

from . import prompts, quiet

logger = logging.getLogger(__name__)

INTROSPECTION_KEY = keys.INTROSPECTION


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


FLOOR_MIN = _env_int("JARVIS_INTROSPECT_FLOOR_MIN", 15)
CAP_MIN = _env_int("JARVIS_INTROSPECT_CAP_MIN", 300)            # 5h
LIGHT_MAX_MIN = _env_int("JARVIS_INTROSPECT_LIGHT_MAX_MIN", 20)
MEDIUM_MAX_MIN = _env_int("JARVIS_INTROSPECT_MEDIUM_MAX_MIN", 80)
# Individual coaching only targets users active within this many hours.
COACHING_ACTIVE_HOURS = _env_int("JARVIS_COACHING_ACTIVE_HOURS", 24)


def depth_for(idle_min: float) -> str:
    """Introspection depth from idle duration (minutes)."""
    if idle_min <= LIGHT_MAX_MIN:
        return "light"
    if idle_min <= MEDIUM_MAX_MIN:
        return "medium"
    return "deep"


def is_clear(response: str) -> bool:
    """True if an introspection response says 'nothing to surface'."""
    text = (response or "").strip()
    return not text or text.upper().startswith(prompts.CLEAR)


def _is_error(response: str) -> bool:
    low = (response or "").lower()
    return low.startswith("erreur") or low.startswith("timeout")


class Introspector:
    """Track B scheduler — adaptive idle introspection + coaching."""

    def __init__(self, claude_runner, notifier, registry):
        self.claude_runner = claude_runner
        self.notifier = notifier
        self.registry = registry
        self._enabled = os.getenv("JARVIS_INTROSPECTION", "true").lower() == "true"
        self._interval_min = FLOOR_MIN
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_seen_activity: datetime | None = None

    # --- lifecycle ---

    async def start(self):
        if not self._enabled:
            logger.info("Introspection disabled (JARVIS_INTROSPECTION=false)")
            return
        self._last_seen_activity = self.registry.last_user_activity()
        self._task = asyncio.create_task(self._loop())
        logger.info("Introspection started (floor=%dmin, cap=%dmin)", FLOOR_MIN, CAP_MIN)

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    def notify_activity(self):
        """Hook called on any genuine user message: reset backoff, wake the loop."""
        self._interval_min = FLOOR_MIN
        self._wake.set()

    # --- internals ---

    async def _sleep(self, minutes: float):
        """Sleep N minutes, returning early if a chat message wakes us."""
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=max(minutes, 0) * 60)
        except asyncio.TimeoutError:
            pass
        finally:
            self._wake.clear()

    def _idle_minutes(self, activity: datetime | None) -> float:
        if activity is None:
            return float(CAP_MIN)  # never any activity → treat as deepest
        return (datetime.now(timezone.utc) - activity).total_seconds() / 60

    async def _loop(self):
        await self._sleep(FLOOR_MIN)  # warm-up
        while True:
            try:
                # Night mode: suppress proactive cycles entirely.
                if quiet.in_quiet_hours(datetime.now()):
                    secs = quiet.seconds_until_quiet_end(datetime.now())
                    logger.debug("Introspection: quiet hours, sleeping %.0fs", secs)
                    await self._sleep(max(secs, 60) / 60)
                    continue

                activity = self.registry.last_user_activity()
                # Fresh chat activity since last cycle → reset and stay reactive.
                if activity and (self._last_seen_activity is None
                                 or activity > self._last_seen_activity):
                    self._last_seen_activity = activity
                    self._interval_min = FLOOR_MIN
                    logger.debug("Introspection: recent chat activity, skipping cycle")
                    await self._sleep(self._interval_min)
                    continue

                idle_min = self._idle_minutes(activity)
                await self._run_cycle(depth_for(idle_min), idle_min)

                # Exponential backoff (Track B only).
                self._interval_min = min(self._interval_min * 2, CAP_MIN)
                await self._sleep(self._interval_min)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Introspection cycle error: %s", e, exc_info=True)
                await self._sleep(self._interval_min)

    async def _run_cycle(self, depth: str, idle_min: float):
        logger.info("Introspection cycle: depth=%s (idle=%.0fmin, next=%dmin)",
                    depth, idle_min, min(self._interval_min * 2, CAP_MIN))

        # Team introspection on the dedicated introspection session.
        response = await self.claude_runner.send_message(
            INTROSPECTION_KEY, prompts.for_depth(depth), with_context=True
        )
        if response and not is_clear(response) and not _is_error(response):
            # Team perimeter review → dedicated coaching channel only (or log-only).
            # Never broadcast into conversation-specific channels.
            await self.notifier.notify_coaching(f"🧭 **Revue d'équipe**\n\n{response}")
            logger.info("Introspection: team review posted (%d chars)", len(response))
        # Keep the introspection session bounded (state lives in memory `global/state`).
        self.claude_runner.clear_session(INTROSPECTION_KEY)

        # Per-conversation tailored coaching: deep cycles only.
        if depth == "deep":
            await self._per_conversation_coaching()

    async def _per_conversation_coaching(self):
        """For each recently-active *user* conversation, generate coaching tailored
        to that conversation's own local context and post it back INTO that
        conversation (cloisonnement). System tracks are skipped."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=COACHING_ACTIVE_HOURS)
        for conv in self.registry.list():
            # Only real user conversations — never monitor:* / introspection.
            if not keys.is_user(conv.key) or not conv.last_activity:
                continue
            try:
                last = datetime.fromisoformat(conv.last_activity)
            except ValueError:
                continue
            if last < cutoff:
                continue
            # Generated WITH this conversation's local context (with_context=True
            # injects conversations/<key>), so suggestions are about its own subject.
            resp = await self.claude_runner.send_message(
                conv.key, prompts.USER_COACHING, with_context=True
            )
            if resp and not is_clear(resp) and not _is_error(resp):
                await self.notifier.notify_conversation(conv.key, f"🧭 {resp}")
                logger.info("Introspection: tailored coaching → %s", conv.key)
