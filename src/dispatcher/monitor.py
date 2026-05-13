"""Proactive monitoring scheduler.

Periodically sends check prompts to Claude Code and dispatches
alerts to all configured channels when issues are detected.
Only runs checks for services that are actually configured.
Pauses checks entirely when an alert is active — resumes only
after the user acknowledges the alert.

In addition to interval-based checks, the scheduler can run
*scheduled* checks at a specific local time (e.g. the daily
morning digest at 08:00).
"""

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from metrics import MONITOR_CHECKS_TOTAL, MONITOR_CHECK_DURATION_SECONDS, MONITOR_CHECK_PAUSED
from services import is_monitor_check_available

logger = logging.getLogger(__name__)

# Monitoring session (separate from user conversations)
MONITOR_SESSION = "jarvis-monitor"

# How often to check if an alert has been acknowledged (seconds)
PAUSED_POLL_INTERVAL = 60


@dataclass
class Check:
    """A periodic or scheduled monitoring check.

    `interval_minutes` and `daily_at` are mutually exclusive:
        - interval_minutes=N  → run every N minutes (after a 60s warm-up)
        - daily_at="HH:MM"    → run once per day at this local time
    `notify_when_clear` makes the check emit a message even when there is
    nothing alarming (useful for the morning digest, which is essentially
    a status report rather than an alert).
    """
    name: str
    prompt: str
    interval_minutes: int = 0
    daily_at: str = ""
    notify_when_clear: bool = False
    required_services: list = field(default_factory=list)


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
    Check(
        name="planka-tasks",
        prompt=(
            "Vérifie les cartes Planka dans les projets MCO, Apps et Home-Assistant. "
            "Regarde s'il y a des cartes dans la liste 'En cours'. "
            "Si oui, traite-les : exécute la tâche décrite, ajoute des commentaires "
            "à chaque étape, puis déplace la carte vers 'Fait' avec un commentaire de synthèse. "
            "C'est un check de monitoring automatique."
        ),
        interval_minutes=5,
    ),
    Check(
        name="gatus-services",
        prompt=(
            "Vérifie l'état des services monitorés par Gatus. "
            "Liste les endpoints et signale ceux qui sont down ou dégradés. "
            "C'est un check de monitoring automatique."
        ),
        interval_minutes=10,
    ),
    Check(
        name="hourly-pulse",
        prompt=(
            "Heartbeat horaire. Fais un balayage rapide de l'état général : "
            "alertes Prometheus actives, pods en CrashLoopBackOff, FluxCD non-Ready, "
            "PVC > 85%, cartes Planka 'En cours' à traiter. "
            "Si tout est calme, réponds 'RAS'. Sinon, sois concis et priorise."
        ),
        interval_minutes=60,
    ),
    Check(
        name="daily-digest",
        daily_at=os.getenv("JARVIS_DAILY_DIGEST_AT", "08:00"),
        notify_when_clear=True,
        prompt=(
            "C'est l'heure du récap matinal. Comporte-toi comme un assistant humain "
            "qui te briefe en arrivant au bureau — pas un rapport technique sec.\n\n"
            "Compare avec la mémoire de la veille (utilise le MCP `memory` : "
            "load_context('digest/last') pour relire ce que tu m'avais raconté hier, "
            "et load_context('repos/<repo>') pour l'état précédent de chaque repo).\n\n"
            "1. **Repos git** : pour chaque repo de GIT_REPOS, liste les commits depuis hier "
            "matin (auteur, message, scope). Mets en valeur les bumps de version, les fix, "
            "les nouvelles features. Compare avec l'état que tu as sauvegardé hier "
            "dans `repos/<repo>`. Mets à jour ce contexte avec le SHA HEAD du jour.\n"
            "2. **Cluster** : changements notables (nouveaux déploiements FluxCD réconciliés, "
            "alertes Prometheus apparues/disparues, incidents en cours).\n"
            "3. **Cartes Planka** : ce qui a bougé dans MCO/Apps/Home-Assistant — "
            "nouvelles cartes, cartes en cours, blocages.\n"
            "4. **À surveiller aujourd'hui** : 1-3 points d'attention concrets.\n\n"
            "Format de sortie : ton conversationnel, paragraphes courts, "
            "tu peux commencer par 'Bonjour' et finir par une question ouverte "
            "type 'tu veux que je creuse l'un de ces points ?'. "
            "Sauvegarde ton récap dans `memory:save_context('digest/last', <ton récap>)` "
            "et dans `memory:save_context('digest/" + datetime.now().strftime("%Y-%m-%d") + "', <ton récap>)` "
            "à la fin (utilise la date du jour réelle au moment où tu écris, pas celle-ci)."
        ),
        required_services=["memory", "git"],
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

    def is_check_paused(self, check_name: str) -> bool:
        """Return True if this check has an active unacknowledged alert."""
        state = self._alert_states.get(check_name)
        return state is not None and not state.acknowledged

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
        """Run a single check on a loop.

        Two pacing modes:
            - check.interval_minutes > 0 → run every N minutes after a 60s warm-up.
            - check.daily_at = "HH:MM"   → sleep until the next local occurrence,
                                            run once, then sleep ~24h.

        When an alert is active and unacknowledged, the check is fully
        paused — no Claude calls, no system queries. It resumes only
        after the user acknowledges the alert via the API.
        """
        if check.daily_at:
            await self._sleep_until_daily(check.daily_at)
        else:
            await asyncio.sleep(60)

        while True:
            # --- Pause while alert is active ---
            if self.is_check_paused(check.name):
                MONITOR_CHECK_PAUSED.labels(check=check.name).set(1)
                logger.debug("Check %s: paused (waiting for user acknowledgment)", check.name)
                await asyncio.sleep(PAUSED_POLL_INTERVAL)
                continue

            MONITOR_CHECK_PAUSED.labels(check=check.name).set(0)

            # --- Run the check ---
            try:
                logger.debug("Running check: %s", check.name)
                session_id = f"{MONITOR_SESSION}-{check.name}"
                with MONITOR_CHECK_DURATION_SECONDS.labels(check=check.name).time():
                    response = await self.claude_runner.send_message(
                        session_id, check.prompt
                    )

                if response and self._is_technical_error(response):
                    # Technical error from Claude Code itself — log and retry next cycle
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="error").inc()
                    logger.warning("Check %s: technical error (not a real alert): %s",
                                   check.name, response[:200])
                elif response and check.notify_when_clear:
                    # Always-emit checks (e.g. daily digest): no alert state, no pause.
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="clear").inc()
                    await self.notifier.notify_all(f"🌅 **{check.name}**\n\n{response}")
                    logger.info("Check %s: digest sent (%d chars)", check.name, len(response))
                elif response and not self._is_all_clear(response):
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="alert").inc()
                    # Issue detected → notify and pause until acknowledged
                    await self.notifier.notify_all(
                        f"🔔 **Monitoring - {check.name}**\n\n{response}\n\n"
                        f"_Check en pause. Acquitter avec `POST /api/alerts/{check.name}/ack`_"
                    )
                    self._record_alert(check.name, response)
                    logger.info("Check %s: alert sent, check paused until acknowledged", check.name)
                else:
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="clear").inc()
                    logger.debug("Check %s: all clear", check.name)
                    # Problem resolved → clear alert state
                    if check.name in self._alert_states:
                        logger.info("Check %s: issue resolved, clearing alert state", check.name)
                        del self._alert_states[check.name]

                # Clear session to avoid context buildup
                self.claude_runner.clear_session(session_id)

            except Exception as e:
                MONITOR_CHECKS_TOTAL.labels(check=check.name, result="error").inc()
                logger.error("Check %s failed: %s", check.name, e)

            if check.daily_at:
                await self._sleep_until_daily(check.daily_at)
            else:
                await asyncio.sleep(check.interval_minutes * 60)

    @staticmethod
    async def _sleep_until_daily(daily_at: str):
        """Sleep until the next local occurrence of HH:MM."""
        try:
            hh, mm = (int(x) for x in daily_at.split(":", 1))
        except ValueError:
            logger.error("Invalid daily_at %r, falling back to 24h sleep", daily_at)
            await asyncio.sleep(24 * 3600)
            return
        now = datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        seconds = (target - now).total_seconds()
        logger.info("Daily check sleeping %.0fs until %s", seconds, target.isoformat(timespec="minutes"))
        await asyncio.sleep(seconds)

    @staticmethod
    def _is_all_clear(response: str) -> bool:
        """Check if the response indicates no issues found."""
        lower = response.lower().strip()
        return any(
            marker in lower
            for marker in ["ras", "rien à signaler", "tout est ok", "tout va bien", "aucun problème"]
        )

    @staticmethod
    def _is_technical_error(response: str) -> bool:
        """Check if the response is a technical error from Claude Code itself,
        not a real monitoring alert. These should be logged, not sent to the user."""
        lower = response.lower().strip()
        return any(
            marker in lower
            for marker in [
                "erreur claude code:",
                "erreur interne:",
                "timeout: claude code",
                "limite de tours",
                "réponse partielle",
            ]
        )
