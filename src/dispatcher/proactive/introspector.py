"""Track B — autonomous introspection with deterministic exponential backoff.

Owns the *cadence* of proactive introspection (the code, not the prompt):

  - firm floor of 15 min; the interval doubles each idle cycle up to a 5h cap;
  - any chat activity resets the interval to the floor and wakes the loop early;
  - fully suppressed during quiet hours (night mode, see `quiet`);
  - depth chosen by idle duration: light (≤20 min) / medium (≤80 min) / deep (>80 min).

When users are actively chatting, introspection is skipped entirely (stay reactive,
don't burn tokens). The "worth saying?" judgment and content live in `prompts`.

Two distinct deliveries (per-conversation isolation doctrine):
  - *perimeter digest* : every cycle that surfaces something updates `global/state`
                    and posts an OPERATOR digest to the dedicated channel only
                    (`notify_coaching`) — never broadcast, and NOT coaching.
  - *coach pass* : deep cycles only → for each recently-active user conversation,
                    apply the `coach` posture (accompaniment) inside THAT
                    conversation's own local context and post the intervention back
                    INTO it (`notify_conversation`). The value≫cost bar in the
                    `coach` prompt means most cycles return RAS and post nothing.
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


FLOOR_MIN = _env_int("JARVIS_INTROSPECT_FLOOR_MIN", 15)
CAP_MIN = _env_int("JARVIS_INTROSPECT_CAP_MIN", 300)            # 5h
LIGHT_MAX_MIN = _env_int("JARVIS_INTROSPECT_LIGHT_MAX_MIN", 20)
MEDIUM_MAX_MIN = _env_int("JARVIS_INTROSPECT_MEDIUM_MAX_MIN", 80)
# Individual coaching only targets users active within this many hours.
COACHING_ACTIVE_HOURS = _env_int("JARVIS_COACHING_ACTIVE_HOURS", 24)
# Gap (hours) between a conversation's last_activity and its context file mtime
# that triggers a stale-context nudge during the deep coach pass.
STALE_CONTEXT_HOURS = _env_int("JARVIS_STALE_CONTEXT_HOURS", 4)


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
        INTROSPECTION_CYCLES_TOTAL.labels(depth=depth).inc()

        # Perimeter introspection on the dedicated introspection session. Its job
        # is to maintain `global/state`; what it surfaces is an OPERATOR digest, not
        # coaching → dedicated operator channel only (or log-only), never broadcast.
        response = await self.claude_runner.send_message(
            INTROSPECTION_KEY, prompts.for_depth(depth), with_context=True
        )
        if response and not is_clear(response) and not _is_error(response):
            await self.notifier.notify_coaching(f"🔭 **Introspection — revue de périmètre**\n\n{response}")
            logger.info("Introspection: perimeter digest posted (%d chars)", len(response))
        # Keep the introspection session bounded (state lives in memory `global/state`).
        self.claude_runner.clear_session(INTROSPECTION_KEY)

        # Coach posture, per conversation: deep cycles only.
        if depth == "deep":
            await self._coach_pass()

    @staticmethod
    def _stale_context_instruction(key: str, last_activity: datetime) -> str:
        """Return a nudge to update a stale memory file, or '' if it is fresh.

        Only fires for conversations whose last_activity is within the coaching
        window — stale contexts for very old conversations are not worth updating.
        """
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
        """Apply the `coach` posture to each recently-active *user* conversation.

        The coaching is generated WITH that conversation's own local context
        (objectives / state / gap / refusals), so an intervention only lands when
        it clears the value≫cost bar — otherwise the prompt returns RAS and nothing
        is posted. Result is delivered INTO that conversation (cloisonnement).
        System tracks are skipped.

        When the conversation's memory file lags its last_activity by more than
        STALE_CONTEXT_HOURS, a stale-context nudge is prepended to the coach prompt
        so Claude updates it before (or instead of) proposing an intervention.
        """
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
            stale = self._stale_context_instruction(conv.key, last)
            prompt = stale + prompts.COACH if stale else prompts.COACH
            resp = await self.claude_runner.send_message(
                conv.key, prompt, with_context=True
            )
            if resp and not is_clear(resp) and not _is_error(resp):
                await self.notifier.notify_conversation(conv.key, f"🧭 {resp}")
                COACH_INTERVENTIONS_TOTAL.inc()
                logger.info("Coach: intervention → %s", conv.key)
                logger.info("Introspection: tailored coaching → %s", conv.key)
