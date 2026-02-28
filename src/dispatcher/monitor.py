"""Proactive monitoring scheduler.

Periodically sends check prompts to Claude Code and dispatches
alerts to all configured channels when issues are detected.
"""

import asyncio
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Monitoring session (separate from user conversations)
MONITOR_SESSION = "jarvis-monitor"


@dataclass
class Check:
    """A periodic monitoring check."""
    name: str
    prompt: str
    interval_minutes: int


# Default checks - can be extended via config
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

    async def start(self):
        if not self._enabled:
            logger.info("Monitoring disabled (JARVIS_MONITORING=false)")
            return

        for check in DEFAULT_CHECKS:
            task = asyncio.create_task(self._run_check_loop(check))
            self._tasks.append(task)

        logger.info(
            "Monitoring started: %d checks",
            len(DEFAULT_CHECKS),
        )

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

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
                    await self.notifier.notify_all(
                        f"🔔 **Monitoring - {check.name}**\n\n{response}"
                    )
                else:
                    logger.debug("Check %s: all clear", check.name)

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
