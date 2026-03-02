"""Proactive monitoring scheduler.

Periodically sends check prompts to Claude Code and dispatches
alerts to all configured channels when issues are detected.
Only runs checks for services that are actually configured.
Avoids repeating the same alerts until the user acknowledges them.
"""

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services import is_monitor_check_available

logger = logging.getLogger(__name__)

# Monitoring session (separate from user conversations)
MONITOR_SESSION = "jarvis-monitor"

# Don't re-send the same alert more than once per this duration (hours)
ALERT_COOLDOWN_HOURS = int(os.getenv("JARVIS_ALERT_COOLDOWN_HOURS", "6"))


@dataclass
class Check:
    """A periodic monitoring check."""
    name: str
    prompt: str
    interval_minutes: int


@dataclass
class AlertState:
    """Tracks the state of a sent alert to avoid repetition."""
    fingerprint: str = ""
    sent_at: datetime | None = None
    acknowledged: bool = False


# Default checks
DEFAULT_CHECKS = [
    Check(
        name="cluster-health",
        prompt=(
            "Fais un check de santé du cluster Kubernetes. "
            "Vérifie : pods en erreur, restarts élevés, nodes en pression, "
            "réconciliations FluxCD en échec, alertes Prometheus actives. "
            "C'est un check de monitoring automatique."
        ),
        interval_minutes=15,
    ),
    Check(
        name="homeassistant",
        prompt=(
            "Vérifie l'état de Home Assistant. "
            "Y a-t-il des entités unavailable, des automations en erreur, "
            "ou des capteurs avec des valeurs anormales ? "
            "C'est un check de monitoring automatique."
        ),
        interval_minutes=30,
    ),
    Check(
        name="fluxcd-reconciliation",
        prompt=(
            "Vérifie l'état de réconciliation de toutes les ressources FluxCD. "
            "GitRepositories, Kustomizations, HelmReleases. "
            "Signale tout ce qui n'est pas Ready. "
            "C'est un check de monitoring automatique."
        ),
        interval_minutes=10,
    ),
]


class Monitor:
    """Runs periodic health checks via Claude Code and dispatches alerts."""

    def __init__(self, claude_runner, notifier):
        self.claude_runner = claude_runner
        self.notifier = notifier
        self._tasks: list[asyncio.Task] = []
        self._enabled = os.getenv("JARVIS_MONITORING", "true").lower() == "true"
        self._alert_states: dict[str, AlertState] = {}

    async def start(self):
        if not self._enabled:
            logger.info("Monitoring disabled (JARVIS_MONITORING=false)")
            return

        active_checks = []
        skipped_checks = []

        for check in DEFAULT_CHECKS:
            if is_monitor_check_available(check.name):
                task = asyncio.create_task(self._run_check_loop(check))
                self._tasks.append(task)
                active_checks.append(check.name)
            else:
                skipped_checks.append(check.name)

        if active_checks:
            logger.info("Monitoring started: %s", ", ".join(active_checks))
        if skipped_checks:
            logger.info("Monitoring checks skipped (services not configured): %s",
                        ", ".join(skipped_checks))

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    def acknowledge_alert(self, check_name: str) -> bool:
        """Mark an alert as acknowledged so the check can report again."""
        if check_name in self._alert_states:
            self._alert_states[check_name].acknowledged = True
            logger.info("Alert acknowledged: %s", check_name)
            return True
        # Acknowledge all if no specific check given
        if check_name == "all":
            for state in self._alert_states.values():
                state.acknowledged = True
            logger.info("All alerts acknowledged")
            return True
        return False

    def _should_notify(self, check_name: str, response: str) -> bool:
        """Decide if we should send this alert or suppress it as a duplicate."""
        fingerprint = self._make_fingerprint(response)
        state = self._alert_states.get(check_name)

        if not state:
            # First alert for this check
            return True

        # Different issue than last time → always notify
        if state.fingerprint != fingerprint:
            return True

        # Same issue but user acknowledged it → it came back, notify again
        if state.acknowledged:
            return True

        # Same issue, not acknowledged → check cooldown
        if state.sent_at:
            hours_since = (datetime.now(timezone.utc) - state.sent_at).total_seconds() / 3600
            if hours_since >= ALERT_COOLDOWN_HOURS:
                # Escalation: re-send after cooldown as a reminder
                logger.info("Alert cooldown expired for %s, re-sending", check_name)
                return True

        # Suppress duplicate
        logger.info("Alert suppressed for %s (same issue, not acknowledged)", check_name)
        return False

    def _record_alert(self, check_name: str, response: str):
        """Record that an alert was sent."""
        self._alert_states[check_name] = AlertState(
            fingerprint=self._make_fingerprint(response),
            sent_at=datetime.now(timezone.utc),
            acknowledged=False,
        )

    @staticmethod
    def _make_fingerprint(response: str) -> str:
        """Create a fingerprint of the alert content.
        Uses a simplified version (first 200 chars) to catch similar but not identical responses."""
        # Normalize: lowercase, strip whitespace, take essence
        normalized = response.lower().strip()[:200]
        return hashlib.md5(normalized.encode()).hexdigest()

    async def _run_check_loop(self, check: Check):
        """Run a single check on a loop."""
        # Wait before first check to let everything initialize
        await asyncio.sleep(60)

        while True:
            try:
                logger.debug("Running check: %s", check.name)
                session_id = f"{MONITOR_SESSION}-{check.name}"
                response = await self.claude_runner.send_message(
                    session_id, check.prompt
                )

                # Only notify if there's something to report (not "RAS")
                if response and not self._is_all_clear(response):
                    if self._should_notify(check.name, response):
                        await self.notifier.notify_all(
                            f"🔔 **Monitoring - {check.name}**\n\n{response}"
                        )
                        self._record_alert(check.name, response)
                else:
                    logger.debug("Check %s: all clear", check.name)
                    # Problem resolved → clear alert state
                    if check.name in self._alert_states:
                        logger.info("Check %s: issue resolved, clearing alert state", check.name)
                        del self._alert_states[check.name]

                # Clear session to avoid context buildup
                self.claude_runner.clear_session(session_id)

            except Exception as e:
                logger.error("Check %s failed: %s", check.name, e)

            await asyncio.sleep(check.interval_minutes * 60)

    @staticmethod
    def _is_all_clear(response: str) -> bool:
        """Check if the response indicates no issues found."""
        lower = response.lower().strip()
        return any(
            marker in lower
            for marker in ["ras", "rien à signaler", "tout est ok", "tout va bien", "aucun problème"]
        )
