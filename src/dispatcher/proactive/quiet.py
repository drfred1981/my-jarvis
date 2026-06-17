"""Quiet-hours (night mode) helpers — shared by both proactive tracks.

During the quiet window, proactive cycles are fully suppressed on BOTH tracks
(infra monitoring AND introspection). Reactive responses to user messages are
unaffected — night mode only silences the agent's self-initiated work.

Window is local time, configured via ``JARVIS_QUIET_HOURS="HH:MM-HH:MM"``
(default ``00:00-07:00``). Wrap-around windows (e.g. ``22:00-07:00``) are supported.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)

_DEFAULT = "00:00-07:00"


def _parse_window(spec: str) -> tuple[time, time]:
    try:
        start_s, end_s = spec.split("-")
        sh, sm = (int(x) for x in start_s.split(":", 1))
        eh, em = (int(x) for x in end_s.split(":", 1))
        return time(sh, sm), time(eh, em)
    except (ValueError, AttributeError):
        logger.warning("quiet: invalid JARVIS_QUIET_HOURS %r, using %s", spec, _DEFAULT)
        return time(0, 0), time(7, 0)


QUIET_START, QUIET_END = _parse_window(os.getenv("JARVIS_QUIET_HOURS", _DEFAULT))


def in_quiet_hours(now: datetime, start: time = QUIET_START, end: time = QUIET_END) -> bool:
    """True if `now` (local) falls inside the quiet window."""
    if start == end:
        return False  # empty window → never quiet
    t = now.time()
    if start < end:
        return start <= t < end
    # wrap-around window (e.g. 22:00 → 07:00)
    return t >= start or t < end


def seconds_until_quiet_end(now: datetime, start: time = QUIET_START,
                            end: time = QUIET_END) -> float:
    """Seconds from `now` until the quiet window ends (0 if not currently quiet)."""
    if not in_quiet_hours(now, start, end):
        return 0.0
    end_dt = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if end_dt <= now:
        end_dt += timedelta(days=1)
    return (end_dt - now).total_seconds()
