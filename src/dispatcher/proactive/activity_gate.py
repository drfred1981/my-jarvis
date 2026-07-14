"""Shared activity gate — coordinates proactive tracks A and B.

Pauses both monitoring (Track A) and introspection (Track B) during Discord
activity, then resumes after INACTIVITY_H of silence using an exponential
backoff schedule:

    1h → 2h → 4h → 8h → 16h → stop

After the 16h cycle returns no new problems, both tracks stop until the next
Discord interaction or detected problem resets the backoff.

Track A (monitor) owns gate advancement via advance().
Track B (introspector) follows the same timing by reading current_interval_h()
after each cycle, and delegates notify_activity() to the gate.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Hours of Discord silence required before background tasks may run.
INACTIVITY_H: float = 1.0

# Exponential backoff sequence (hours): 1 → 2 → 4 → 8 → 16 → stop.
BACKOFF_H: list[int] = [1, 2, 4, 8, 16]


class ActivityGate:
    """Shared backoff controller for Track A (monitor) and Track B (introspector).

    Track A calls advance(found_problem=...) after each batch run.
    Track B reads current_interval_h() to decide how long to sleep.
    Both await wait_for_opening() to block while the user is active in Discord.
    Both await wait_for_unblock() when is_stopped() is True.
    """

    def __init__(self, registry) -> None:
        self._registry = registry
        self._idx = 0           # current position in BACKOFF_H
        self._stopped = False   # True after 16h cycle clears → wait for activity
        self._wake = asyncio.Event()

    # --- external hooks ---

    def notify_activity(self) -> None:
        """Call on any Discord user message: reset backoff and unblock sleeps."""
        if self._stopped or self._idx > 0:
            logger.debug("ActivityGate: Discord activity → reset backoff to 1h")
        self._idx = 0
        self._stopped = False
        self._wake.set()

    def notify_problem(self) -> None:
        """Call when a background check surfaces a new alert: reset backoff."""
        self._idx = 0
        self._stopped = False
        self._wake.set()

    # --- state queries ---

    def is_stopped(self) -> bool:
        """True after the 16h cycle with no problems (until next user activity)."""
        return self._stopped

    def current_interval_h(self) -> float:
        """Current wait interval in hours before next background run. inf when stopped."""
        return float("inf") if self._stopped else float(BACKOFF_H[min(self._idx, len(BACKOFF_H) - 1)])

    def is_user_active(self) -> bool:
        """True if a Discord user was active within the last INACTIVITY_H hours."""
        last = self._registry.last_user_activity()
        if last is None:
            return False
        elapsed_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return elapsed_h < INACTIVITY_H

    # --- Track A: advance after each monitor batch ---

    def advance(self, *, found_problem: bool) -> None:
        """Step the backoff forward after a monitor batch run.

        found_problem=True  → reset to index 0 (next run in 1h).
        found_problem=False at last step (16h) → set stopped.
        found_problem=False otherwise → step to next interval.
        """
        if found_problem:
            self._idx = 0
            self._stopped = False
            logger.debug("ActivityGate: problem detected → backoff reset to 1h")
        elif self._idx >= len(BACKOFF_H) - 1:
            self._stopped = True
            logger.info(
                "ActivityGate: 16h cycle all-clear → background tasks stopped "
                "(will resume on next Discord interaction)"
            )
        else:
            self._idx += 1
            logger.debug("ActivityGate: all-clear → next batch interval %dh", BACKOFF_H[self._idx])

    # --- async helpers ---

    async def wait_for_opening(self) -> None:
        """Block until the user has been idle for at least INACTIVITY_H hours.

        Returns immediately if already idle long enough.
        Wakes early on notify_activity() — which resets the clock so we
        re-enter the wait for the full INACTIVITY_H period again.
        """
        while self.is_user_active():
            last = self._registry.last_user_activity()
            wait_s = 120.0
            if last is not None:
                next_open = last + timedelta(hours=INACTIVITY_H)
                wait_s = max(60.0, (next_open - datetime.now(timezone.utc)).total_seconds())
            logger.debug("ActivityGate: user active — waiting %.0fs for inactivity window", wait_s)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait_s)
            except asyncio.TimeoutError:
                pass
            finally:
                self._wake.clear()

    async def wait_for_unblock(self) -> None:
        """Block until is_stopped() becomes False (activity or problem resets gate)."""
        while self._stopped:
            logger.debug("ActivityGate: stopped — waiting for Discord activity to resume")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=3600.0)
            except asyncio.TimeoutError:
                pass
            finally:
                self._wake.clear()
