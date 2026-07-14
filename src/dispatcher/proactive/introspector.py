"""Track B — autonomous introspection with activity-gated exponential backoff.

Scheduling model (coordinated with ActivityGate / Track A):

  - Blocked while a Discord user was active in the last 1h (gate.wait_for_opening).
  - On first opening: runs a cycle (depth depends on idle duration).
  - Backoff shared with Track A: 1h → 2h → 4h → 8h → 16h.
    Track A owns gate.advance(); Track B reads gate.current_interval_h() to sleep.
  - When gate.is_stopped() (16h all-clear): Track B also goes silent
    (except in night mode — see below).
  - Reset on any Discord activity (notify_activity → gate.notify_activity +
    wake own sleep early).

Night mode (00h–07h):
  - Instead of full suppression, Track B runs ONE deep introspection + coaching
    cycle at the start of the quiet window, then sleeps until morning.
  - This lets the agent review its state and coach conversations during the
    quietest period — without disturbing the user.

Depth chosen by idle duration:
  - ≤ 20 min → light
  - ≤ 80 min → medium
  - > 80 min → deep (also triggers _coach_pass per conversation)

Two distinct deliveries (per-conversation isolation doctrine):
  - perimeter digest : every non-clear cycle → `global/state` update + notify_coaching.
  - coach pass       : deep cycles only → per active conversation, via notify_conversation.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from conversations import keys
from context.injector import MEMORY_DIR, local_context_name
from metrics import (
    INTROSPECTION_CYCLES_TOTAL,
    COACH_INTERVENTIONS_TOTAL,
    STALE_CONTEXTS_DETECTED_TOTAL,
)

from . import prompts, quiet

logger = logging.getLogger(__name__)

INTROSPECTION_KEY = keys.INTROSPECTION


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


LIGHT_MAX_MIN = _env_int("JARVIS_INTROSPECT_LIGHT_MAX_MIN", 20)
MEDIUM_MAX_MIN = _env_int("JARVIS_INTROSPECT_MEDIUM_MAX_MIN", 80)
# Coaching window: only coach conversations active within this many hours.
COACHING_ACTIVE_HOURS = _env_int("JARVIS_COACHING_ACTIVE_HOURS", 24)
# Gap (hours) between last_activity and context file mtime that triggers a stale nudge.
STALE_CONTEXT_HOURS = _env_int("JARVIS_STALE_CONTEXT_HOURS", 4)

# Warm-up sleep before first introspection cycle (minutes).
_WARMUP_MIN = _env_int("JARVIS_INTROSPECT_WARMUP_MIN", 60)


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
    """Track B scheduler — activity-gated introspection + coaching.

    Requires an ActivityGate (gate) for coordinated timing with Track A.
    Without a gate it falls back to the legacy 15min→5h per-track backoff.
    """

    def __init__(self, claude_runner, notifier, registry, gate=None):
        self.claude_runner = claude_runner
        self.notifier = notifier
        self.registry = registry
        self._gate = gate
        self._enabled = os.getenv("JARVIS_INTROSPECTION", "true").lower() == "true"
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        # Legacy fallback state (used only when gate=None).
        self._interval_min = _env_int("JARVIS_INTROSPECT_FLOOR_MIN", 15)
        self._cap_min = _env_int("JARVIS_INTROSPECT_CAP_MIN", 300)

    # --- lifecycle ---

    async def start(self):
        if not self._enabled:
            logger.info("Introspection disabled (JARVIS_INTROSPECTION=false)")
            return
        self._task = asyncio.create_task(self._loop())
        if self._gate:
            logger.info("Introspection started (gate-coordinated, 1h→2h→4h→8h→16h backoff)")
        else:
            logger.info("Introspection started (legacy mode, floor=%dmin, cap=%dmin)",
                        self._interval_min, self._cap_min)

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    def notify_activity(self) -> None:
        """Hook called on any genuine user message: reset backoff, wake loop early."""
        if self._gate:
            self._gate.notify_activity()
        else:
            self._interval_min = _env_int("JARVIS_INTROSPECT_FLOOR_MIN", 15)
        self._wake.set()

    # --- internals ---

    async def _sleep(self, minutes: float) -> None:
        """Sleep N minutes, returning early if activity wakes us."""
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=max(minutes, 0) * 60)
        except asyncio.TimeoutError:
            pass
        finally:
            self._wake.clear()

    def _idle_minutes(self, activity: datetime | None) -> float:
        if activity is None:
            return 9999.0  # no activity ever → deepest mode
        return (datetime.now(timezone.utc) - activity).total_seconds() / 60

    async def _loop(self):
        await self._sleep(_WARMUP_MIN)  # let the service fully start

        if self._gate:
            await self._loop_gated()
        else:
            await self._loop_legacy()

    async def _loop_gated(self):
        """Main introspection loop coordinated with ActivityGate."""
        _night_done_today: str | None = None  # date "YYYY-MM-DD" of last night cycle

        while True:
            try:
                now = datetime.now()

                # --- Night mode: ONE deep cycle per night, then sleep until morning ---
                if quiet.in_quiet_hours(now):
                    today = now.strftime("%Y-%m-%d")
                    if _night_done_today != today:
                        _night_done_today = today
                        activity = self.registry.last_user_activity()
                        idle_min = self._idle_minutes(activity)
                        logger.info(
                            "Introspection: night mode — running deep cycle (idle=%.0fmin)", idle_min
                        )
                        await self._run_cycle("deep", idle_min)

                    secs = quiet.seconds_until_quiet_end(now)
                    if secs > 60:
                        logger.debug(
                            "Introspection: night deep done, sleeping %.0fs until morning", secs
                        )
                        await self._sleep(secs / 60)
                    continue

                # --- Stopped: gate exhausted 16h all-clear → wait for activity ---
                if self._gate.is_stopped():
                    logger.debug("Introspection: gate stopped — waiting for Discord activity")
                    await self._gate.wait_for_unblock()
                    continue

                # --- Gated: wait for 1h of user inactivity ---
                await self._gate.wait_for_opening()

                # Re-check night mode (could have become night while waiting).
                if quiet.in_quiet_hours(datetime.now()):
                    continue

                # --- Run cycle ---
                activity = self.registry.last_user_activity()
                idle_min = self._idle_minutes(activity)
                await self._run_cycle(depth_for(idle_min), idle_min)

                # --- Sleep gate's current interval (set by Track A's advance()) ---
                interval_h = self._gate.current_interval_h()
                if interval_h == float("inf"):
                    continue  # gate stopped → next loop iteration handles it
                logger.debug("Introspection: sleeping %.0fh until next cycle", interval_h)
                await self._sleep(interval_h * 60)  # _sleep takes minutes

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Introspection cycle error: %s", e, exc_info=True)
                await self._sleep(60)

    async def _loop_legacy(self):
        """Legacy loop (no gate): 15min→5h per-track backoff, night suppression."""
        while True:
            try:
                if quiet.in_quiet_hours(datetime.now()):
                    secs = quiet.seconds_until_quiet_end(datetime.now())
                    logger.debug("Introspection (legacy): quiet hours, sleeping %.0fs", secs)
                    await self._sleep(max(secs, 60) / 60)
                    continue

                activity = self.registry.last_user_activity()
                idle_min = self._idle_minutes(activity)
                await self._run_cycle(depth_for(idle_min), idle_min)

                self._interval_min = min(self._interval_min * 2, self._cap_min)
                await self._sleep(self._interval_min)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Introspection (legacy) error: %s", e, exc_info=True)
                await self._sleep(self._interval_min)

    async def _run_cycle(self, depth: str, idle_min: float):
        if self._gate:
            next_h = self._gate.current_interval_h()
            next_info = f"{next_h:.0f}h" if next_h != float("inf") else "stopped"
        else:
            next_info = f"{min(self._interval_min * 2, self._cap_min):.0f}min"

        logger.info("Introspection cycle: depth=%s (idle=%.0fmin, next=%s)",
                    depth, idle_min, next_info)
        INTROSPECTION_CYCLES_TOTAL.labels(depth=depth).inc()

        response = await self.claude_runner.send_message(
            INTROSPECTION_KEY, prompts.for_depth(depth), with_context=True
        )
        if response and not is_clear(response) and not _is_error(response):
            await self.notifier.notify_coaching(f"🔭 **Introspection — revue de périmètre**\n\n{response}")
            logger.info("Introspection: perimeter digest posted (%d chars)", len(response))
        self.claude_runner.clear_session(INTROSPECTION_KEY)

        if depth == "deep":
            await self._coach_pass()

    @staticmethod
    def _stale_context_instruction(key: str, last_activity: datetime) -> str:
        now = datetime.now(timezone.utc)
        if (now - last_activity).total_seconds() / 3600 > COACHING_ACTIVE_HOURS:
            return ""
        ctx_name = local_context_name(key)
        parts = [seg for seg in ctx_name.strip("/").split("/") if seg]
        path = os.path.join(MEMORY_DIR, *parts) + ".md"
        if not os.path.isfile(path):
            STALE_CONTEXTS_DETECTED_TOTAL.labels(reason="missing").inc()
            return (
                f"⚠️ La mémoire locale `{ctx_name}` n'existe pas encore. "
                f"Crée-la via `memory:save_context` (objectifs, état, historique, "
                f"refus/préférences) avant de décider s'il y a une intervention coach.\n\n"
            )
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        gap_h = (last_activity - mtime).total_seconds() / 3600
        if gap_h > STALE_CONTEXT_HOURS:
            STALE_CONTEXTS_DETECTED_TOTAL.labels(reason="outdated").inc()
            return (
                f"⚠️ La mémoire locale `{ctx_name}` accuse ~{gap_h:.0f}h de retard "
                f"sur les derniers échanges. Mets-la à jour via `memory:save_context` "
                f"avant l'évaluation coach.\n\n"
            )
        return ""

    async def _coach_pass(self):
        """Apply the `coach` posture to each recently-active user conversation.

        Coaching is generated WITH that conversation's own local context and
        delivered INTO it (cloisonnement). System tracks are skipped.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=COACHING_ACTIVE_HOURS)
        for conv in self.registry.list():
            if not keys.is_user(conv.key) or not conv.last_activity:
                continue
            try:
                last = datetime.fromisoformat(conv.last_activity)
            except ValueError:
                continue
            if last < cutoff:
                continue
            stale = self._stale_context_instruction(conv.key, last)
            prompt = stale + prompts.COACH if stale else prompts.COACH
            resp = await self.claude_runner.send_message(
                conv.key, prompt, with_context=True
            )
            if resp and not is_clear(resp) and not _is_error(resp):
                await self.notifier.notify_conversation(conv.key, f"🧭 {resp}")
                COACH_INTERVENTIONS_TOTAL.inc()
                logger.info("Coach: intervention → %s", conv.key)
