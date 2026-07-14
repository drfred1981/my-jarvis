"""Proactive monitoring scheduler — Track A.

Runs infra checks via Claude Code and dispatches alerts to the dedicated
monitoring channel. Never broadcasts into conversation-specific channels.

Scheduling model (activity-gated backoff):
  - All interval-based checks run as a single batch, controlled by an
    ActivityGate shared with the introspector:
      * blocked while a Discord user was active in the last 1h
      * on first opening: runs a batch of all interval checks
      * backoff: 1h → 2h → 4h → 8h → 16h → stop (if all-clear)
      * reset on any detected problem or user activity
  - Daily-scheduled checks (daily_at="HH:MM") keep their own independent
    clock and are not affected by the gate.

Night mode: the gate naturally handles night (no user activity → gate
opens on its backoff schedule). No explicit night suppression for interval
checks. Daily checks retain their own schedule (08:00 digest, etc.).

Alert behaviour (unchanged):
  - On problem detected → notify, record alert, call gate.notify_problem().
  - Batch pauses while any alert is unacknowledged.
  - User acknowledges via POST /api/alerts/{name}/ack.
"""

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from conversations import keys
from metrics import MONITOR_CHECKS_TOTAL, MONITOR_CHECK_DURATION_SECONDS, MONITOR_CHECK_PAUSED
from services import is_monitor_check_available

logger = logging.getLogger(__name__)

# How often to poll for alert acknowledgement (seconds).
PAUSED_POLL_INTERVAL = 60


@dataclass
class Check:
    """A periodic or scheduled monitoring check.

    `interval_minutes` and `daily_at` are mutually exclusive:
        - interval_minutes=N  → included in the batch loop (gate-controlled)
        - daily_at="HH:MM"    → run once per day at this local time (independent clock)
    `notify_when_clear` makes the check emit a message even when all is fine
    (used for the morning digest, which is a status report, not an alert).
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
            "à la fin (utilise la date du jour réelle au moment où tu écris, pas celle-ci).\n\n"
            "Archive aussi ce récap dans Trilium :\n"
            "1. `trilium:search_notes('note.title=\'Digests\'')`→ cherche la note 'Digests'.\n"
            "2. Si absente : `trilium:search_notes('note.title=\'Jarvis\'')`→ récupère l'ID Jarvis, "
            "puis `trilium:create_note(parent_note_id=<jarvis_id>, title='Digests', content='')`.\n"
            "3. Crée la note du jour : `trilium:create_note(parent_note_id=<digests_id>, "
            "title='Digest <date YYYY-MM-DD>', content=<récap en HTML>, "
            "note_type='text', content_type='text/html')`."
        ),
        required_services=["memory", "git", "trilium"],
    ),
]


class Monitor:
    """Runs periodic health checks via Claude Code and dispatches alerts.

    Pass an ActivityGate instance to enable activity-gated batch scheduling.
    Without a gate the monitor falls back to fixed-interval per-check loops
    (legacy behaviour, kept for gate-less deployments).
    """

    def __init__(self, claude_runner, notifier, archiver=None, gate=None):
        self.claude_runner = claude_runner
        self.notifier = notifier
        self._archiver = archiver
        self._gate = gate
        self._tasks: list[asyncio.Task] = []
        self._enabled = os.getenv("JARVIS_MONITORING", "true").lower() == "true"
        self._alert_states: dict[str, AlertState] = {}

    async def start(self):
        if not self._enabled:
            logger.info("Monitoring disabled (JARVIS_MONITORING=false)")
            return

        interval_checks = []
        daily_checks = []
        skipped = []

        for check in DEFAULT_CHECKS:
            if not is_monitor_check_available(check.name):
                skipped.append(check.name)
                continue
            if check.daily_at:
                daily_checks.append(check)
            else:
                interval_checks.append(check)

        if interval_checks:
            if self._gate:
                task = asyncio.create_task(self._run_batch_loop(interval_checks))
                self._tasks.append(task)
            else:
                for check in interval_checks:
                    task = asyncio.create_task(self._run_check_loop(check))
                    self._tasks.append(task)
            logger.info("Monitoring interval checks: %s", ", ".join(c.name for c in interval_checks))

        for check in daily_checks:
            task = asyncio.create_task(self._run_check_loop(check))
            self._tasks.append(task)
            logger.info("Monitoring daily check: %s at %s", check.name, check.daily_at)

        if skipped:
            logger.info("Monitoring checks skipped (services not configured): %s", ", ".join(skipped))

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
        if check_name == "all":
            for state in self._alert_states.values():
                state.acknowledged = True
            logger.info("All alerts acknowledged")
            return True
        return False

    def is_check_paused(self, check_name: str) -> bool:
        """True if this check has an active unacknowledged alert."""
        state = self._alert_states.get(check_name)
        return state is not None and not state.acknowledged

    def _record_alert(self, check_name: str, response: str):
        self._alert_states[check_name] = AlertState(
            fingerprint=self._make_fingerprint(response),
            sent_at=datetime.now(timezone.utc),
            acknowledged=False,
        )

    @staticmethod
    def _make_fingerprint(response: str) -> str:
        normalized = response.lower().strip()[:200]
        return hashlib.md5(normalized.encode()).hexdigest()

    def _archive_result(self, check_name: str, response: str) -> None:
        if self._archiver:
            import asyncio as _asyncio
            _asyncio.create_task(
                _asyncio.to_thread(
                    self._archiver.archive_monitor_result, check_name, response
                )
            )

    # --- batch loop (gate-controlled) ---

    async def _run_batch_loop(self, checks: list):
        """Run all interval checks as one batch, paced by ActivityGate.

        Schedule:
          1. If gate is stopped → block until Discord activity resets it.
          2. Wait until user has been idle for 1h (gate.wait_for_opening).
          3. Skip if any check has an unacknowledged alert (poll every 60s).
          4. Run all checks sequentially; detect problems.
          5. Advance gate (found_problem drives backoff or stop).
          6. Sleep gate.current_interval_h() hours.
          7. Back to 1.
        """
        await asyncio.sleep(60)  # warm-up

        while True:
            try:
                # --- stopped: gate exhausted after 16h all-clear ---
                if self._gate.is_stopped():
                    logger.info("Monitor: gate stopped — waiting for Discord activity")
                    await self._gate.wait_for_unblock()

                # --- gated: wait for 1h of user inactivity ---
                await self._gate.wait_for_opening()

                # --- paused: wait while any alert is unacknowledged ---
                paused_checks = [c for c in checks if self.is_check_paused(c.name)]
                if paused_checks:
                    for c in paused_checks:
                        MONITOR_CHECK_PAUSED.labels(check=c.name).set(1)
                    logger.debug(
                        "Monitor batch: paused (unacknowledged: %s)",
                        [c.name for c in paused_checks],
                    )
                    await asyncio.sleep(PAUSED_POLL_INTERVAL)
                    continue

                for c in checks:
                    MONITOR_CHECK_PAUSED.labels(check=c.name).set(0)

                # --- run all checks ---
                logger.info(
                    "Monitor batch: running %d checks (gate interval %dh)",
                    len(checks),
                    int(self._gate.current_interval_h()),
                )
                found_problem = False
                for check in checks:
                    if self.is_check_paused(check.name):
                        continue  # a previous check in this batch triggered an alert
                    problem = await self._run_one_check(check)
                    if problem:
                        found_problem = True

                # --- advance gate ---
                self._gate.advance(found_problem=found_problem)

                if not self._gate.is_stopped():
                    interval_h = self._gate.current_interval_h()
                    logger.info(
                        "Monitor batch done (problem=%s). Next in %.0fh.",
                        found_problem, interval_h,
                    )
                    await asyncio.sleep(interval_h * 3600)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Monitor batch loop error: %s", e, exc_info=True)
                await asyncio.sleep(300)

    async def _run_one_check(self, check: Check) -> bool:
        """Execute a single check. Returns True if a problem was detected and alerted."""
        try:
            logger.debug("Monitor: running check %s", check.name)
            session_id = keys.monitor(check.name)
            with MONITOR_CHECK_DURATION_SECONDS.labels(check=check.name).time():
                response = await self.claude_runner.send_message(session_id, check.prompt)

            if response and self._is_technical_error(response):
                MONITOR_CHECKS_TOTAL.labels(check=check.name, result="error").inc()
                logger.warning("Check %s: technical error: %s", check.name, response[:200])
                return False

            if response and not self._is_all_clear(response):
                MONITOR_CHECKS_TOTAL.labels(check=check.name, result="alert").inc()
                await self.notifier.notify_monitoring(
                    f"\U0001f514 **Monitoring - {check.name}**\n\n{response}\n\n"
                    f"_Check en pause. Acquitter avec `POST /api/alerts/{check.name}/ack`_"
                )
                self._record_alert(check.name, response)
                self._archive_result(check.name, response)
                if self._gate:
                    self._gate.notify_problem()
                logger.info("Check %s: alert sent, check paused until acknowledged", check.name)
                return True

            MONITOR_CHECKS_TOTAL.labels(check=check.name, result="clear").inc()
            if check.name in self._alert_states:
                logger.info("Check %s: issue resolved, clearing alert state", check.name)
                del self._alert_states[check.name]
            logger.debug("Check %s: all clear", check.name)
            return False

        except Exception as e:
            MONITOR_CHECKS_TOTAL.labels(check=check.name, result="error").inc()
            logger.error("Check %s failed: %s", check.name, e)
            return False
        finally:
            self.claude_runner.clear_session(keys.monitor(check.name))

    # --- legacy per-check loop (daily checks + gate-less fallback) ---

    async def _run_check_loop(self, check: Check):
        """Single-check loop for daily-scheduled checks and gate-less fallback."""
        if check.daily_at:
            await self._sleep_until_daily(check.daily_at)
        else:
            await asyncio.sleep(60)

        while True:
            if self.is_check_paused(check.name):
                MONITOR_CHECK_PAUSED.labels(check=check.name).set(1)
                logger.debug("Check %s: paused (waiting for acknowledgment)", check.name)
                await asyncio.sleep(PAUSED_POLL_INTERVAL)
                continue

            MONITOR_CHECK_PAUSED.labels(check=check.name).set(0)

            try:
                logger.debug("Running check: %s", check.name)
                session_id = keys.monitor(check.name)
                with MONITOR_CHECK_DURATION_SECONDS.labels(check=check.name).time():
                    response = await self.claude_runner.send_message(session_id, check.prompt)

                if response and self._is_technical_error(response):
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="error").inc()
                    logger.warning("Check %s: technical error: %s", check.name, response[:200])
                elif response and check.notify_when_clear:
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="clear").inc()
                    await self.notifier.notify_monitoring(f"\U0001f305 **{check.name}**\n\n{response}")
                    self._archive_result(check.name, response)
                    logger.info("Check %s: digest sent (%d chars)", check.name, len(response))
                elif response and not self._is_all_clear(response):
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="alert").inc()
                    await self.notifier.notify_monitoring(
                        f"\U0001f514 **Monitoring - {check.name}**\n\n{response}\n\n"
                        f"_Check en pause. Acquitter avec `POST /api/alerts/{check.name}/ack`_"
                    )
                    self._record_alert(check.name, response)
                    self._archive_result(check.name, response)
                    if self._gate:
                        self._gate.notify_problem()
                    logger.info("Check %s: alert sent, paused until acknowledged", check.name)
                else:
                    MONITOR_CHECKS_TOTAL.labels(check=check.name, result="clear").inc()
                    logger.debug("Check %s: all clear", check.name)
                    if check.name in self._alert_states:
                        logger.info("Check %s: issue resolved", check.name)
                        del self._alert_states[check.name]

                self.claude_runner.clear_session(session_id)

            except Exception as e:
                MONITOR_CHECKS_TOTAL.labels(check=check.name, result="error").inc()
                logger.error("Check %s failed: %s", check.name, e)

            if check.daily_at:
                await self._sleep_until_daily(check.daily_at)
            else:
                from proactive import quiet as _quiet
                if _quiet.in_quiet_hours(datetime.now()):
                    secs = _quiet.seconds_until_quiet_end(datetime.now())
                    await asyncio.sleep(max(secs, 60))
                else:
                    await asyncio.sleep(max(check.interval_minutes, 15) * 60)

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
        lower = response.lower().strip()
        return any(
            marker in lower
            for marker in ["ras", "rien \xe0 signaler", "tout est ok", "tout va bien", "aucun probl\xe8me"]
        )

    @staticmethod
    def _is_technical_error(response: str) -> bool:
        lower = response.lower().strip()
        return any(
            marker in lower
            for marker in [
                "erreur claude code:",
                "erreur interne:",
                "timeout: claude code",
                "limite de tours",
                "r\xe9ponse partielle",
            ]
        )
