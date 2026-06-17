"""Interface with Claude Code CLI to process messages."""

import asyncio
import json
import logging
import os

from context import injector
from conversations import ConversationRegistry, keys
from metrics import ACTIVE_SESSIONS
from services import get_active_services, get_active_mcp_config, get_allowed_tools_string

logger = logging.getLogger(__name__)

# Working directory where CLAUDE.md and MCP settings live
JARVIS_PROJECT_DIR = os.environ.get(
    "JARVIS_PROJECT_DIR", "/home/jarvis"
)

# MCP config file path (base config, will be filtered at runtime)
MCP_CONFIG = os.path.join(JARVIS_PROJECT_DIR, "mcp.json")

# Durable conversation index (survives restarts, next to native sessions)
CONVERSATIONS_INDEX = os.path.join(
    JARVIS_PROJECT_DIR, ".claude", "conversations-index.json"
)

# Max budget per request (USD)
MAX_BUDGET = os.environ.get("JARVIS_MAX_BUDGET", "1.00")

# Max agentic turns per request
MAX_TURNS = os.environ.get("JARVIS_MAX_TURNS", "25")

# Timeout per request (seconds).
# Default 3600s (1h) to accommodate the daily-digest and complex incident
# investigations. Override via the JARVIS_TIMEOUT env var if needed.
TIMEOUT = int(os.environ.get("JARVIS_TIMEOUT", "3600"))


class ClaudeRunner:
    """Runs Claude Code CLI commands and manages conversation sessions.

    Conversation state (the mapping key → Claude session id + activity) lives in
    a durable `ConversationRegistry`, so `--resume` continuity and idle tracking
    survive restarts. Callers address conversations by their structured key
    (see `conversations.keys`).
    """

    def __init__(self, registry: ConversationRegistry | None = None):
        self.registry = registry or ConversationRegistry(CONVERSATIONS_INDEX)
        self._lock = asyncio.Lock()
        self._runtime_mcp_config: str | None = None
        self._activity_listeners: list = []
        ACTIVE_SESSIONS.set(self.registry.count())

    def add_activity_listener(self, callback) -> None:
        """Register a callback fired on every genuine user message (e.g. to wake
        the introspector and reset its backoff). Called with no arguments."""
        self._activity_listeners.append(callback)

    def _get_mcp_config_path(self) -> str | None:
        """Generate a filtered mcp.json with only active services."""
        if not os.path.isfile(MCP_CONFIG):
            return None

        active_config = get_active_mcp_config(MCP_CONFIG)
        if not active_config.get("mcpServers"):
            logger.warning("No MCP services configured, Claude will run without tools")
            return None

        # Write filtered config to a fixed path (avoids /tmp cleanup issues)
        path = os.path.join(JARVIS_PROJECT_DIR, ".claude", "mcp-runtime.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(active_config, f, indent=2)
        self._runtime_mcp_config = path
        return path

    async def send_message(self, conversation_key: str, message: str,
                           *, with_context: bool = True,
                           is_user_initiated: bool = False,
                           heartbeat=None, heartbeat_interval: float = 30) -> str:
        """Send a message to Claude Code and return the response.

        `conversation_key` is a structured key (see `conversations.keys`), e.g.
        ``discord:dm:123`` or ``monitor:cluster-health``. When `with_context` is
        set, the distilled local + global context is prepended to the message
        (no-op until those memory contexts exist). `is_user_initiated` marks a
        genuine inbound user message — only those update last-activity and wake
        the introspector (agent-initiated sends, e.g. coaching, must not).

        `heartbeat`, if given, is an async callback ``cb(elapsed_seconds)`` invoked
        every `heartbeat_interval` s while the run is in flight (long-task UX).
        """
        logger.info("Processing message for %s: %s", conversation_key, message[:100])

        async with self._lock:
            conv = self.registry.get_or_create(conversation_key)
            if is_user_initiated:
                self.registry.touch(conversation_key)
            ACTIVE_SESSIONS.set(self.registry.count())

        # Signal genuine user activity (wakes the introspector / resets backoff).
        if is_user_initiated and keys.is_user(conversation_key):
            for cb in self._activity_listeners:
                try:
                    cb()
                except Exception as e:
                    logger.warning("activity listener error: %s", e)

        # Prepend distilled local + global context (bounded, no-op if absent)
        prompt = injector.inject(conversation_key, message) if with_context else message

        # Detect active services
        active_services = get_active_services()
        logger.info("Active MCP services: %s", active_services or "none")

        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "json",
            "--max-turns", MAX_TURNS,
            "--max-budget-usd", MAX_BUDGET,
        ]

        # Load only active MCP servers
        mcp_path = self._get_mcp_config_path()
        if mcp_path:
            cmd.extend(["--mcp-config", mcp_path])

        # Allow tools only for active services
        if active_services:
            allowed = get_allowed_tools_string(active_services)
            cmd.extend(["--allowedTools", allowed])

        # Resume existing conversation
        if conv.claude_session_id:
            cmd.extend(["--resume", conv.claude_session_id])

        logger.info("Running: %s (cwd=%s)", " ".join(cmd[:6]) + " ...", JARVIS_PROJECT_DIR)

        env = os.environ.copy()

        hb_task = (asyncio.create_task(self._heartbeat_loop(heartbeat, heartbeat_interval))
                   if heartbeat else None)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=JARVIS_PROJECT_DIR,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT
            )

            stderr_text = stderr.decode().strip()
            if stderr_text:
                logger.info("Claude Code stderr: %s", stderr_text[:500])

            output = stdout.decode().strip()

            if proc.returncode != 0 and not output:
                logger.error("Claude Code error (rc=%d): %s", proc.returncode, stderr_text)
                return f"Erreur Claude Code: {stderr_text or 'processus terminé sans réponse'}"

            response_text = self._parse_claude_output(output, stderr_text)

            # Capture session ID for conversation continuity (persisted)
            try:
                result = json.loads(output)
                claude_sid = result.get("session_id")
                if claude_sid:
                    async with self._lock:
                        self.registry.record_session_id(conversation_key, claude_sid)
            except (json.JSONDecodeError, AttributeError):
                pass

            return response_text

        except asyncio.TimeoutError:
            logger.error("Claude Code timeout for %s", conversation_key)
            return f"Timeout: Claude Code n'a pas répondu dans les {TIMEOUT} secondes."
        except Exception as e:
            logger.error("Claude Code exception: %s", e)
            return f"Erreur interne: {e}"
        finally:
            if hb_task:
                hb_task.cancel()

    @staticmethod
    async def _heartbeat_loop(callback, interval: float):
        """Invoke `callback(elapsed_seconds)` every `interval` s until cancelled."""
        elapsed = 0.0
        try:
            while True:
                await asyncio.sleep(interval)
                elapsed += interval
                try:
                    await callback(elapsed)
                except Exception as e:
                    logger.debug("heartbeat callback error: %s", e)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _parse_claude_output(output: str, stderr_text: str = "") -> str:
        """Parse Claude Code JSON output into a user-friendly response."""
        if not output:
            return f"Erreur Claude Code: {stderr_text or 'aucune réponse'}"

        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            # Not JSON, return raw output
            return output

        # Extract the text response if present
        response_text = result.get("result", "")

        subtype = result.get("subtype", "")
        is_error = result.get("is_error", False)

        if response_text:
            # Got a response, but maybe hit limits
            if subtype == "error_max_turns":
                return response_text + "\n\n_(Réponse partielle : limite de tours atteinte)_"
            return response_text

        # No result field — handle known error subtypes
        if subtype == "error_max_turns":
            cost = result.get("total_cost_usd", 0)
            turns = result.get("num_turns", 0)
            logger.warning("Claude hit max turns (%d, cost=$%.2f)", turns, cost)
            return (
                "Désolé, la tâche était trop complexe et j'ai atteint la limite de tours "
                f"({turns} tours, ${cost:.2f}). "
                "Essaie de reformuler avec une demande plus ciblée."
            )

        if is_error:
            errors = result.get("errors", [])
            error_msg = "; ".join(str(e) for e in errors) if errors else "erreur inconnue"
            return f"Erreur Claude Code: {error_msg}"

        # Fallback — don't dump raw JSON to users
        logger.warning("Unexpected Claude output format: %s", output[:200])
        return "Désolé, je n'ai pas pu traiter cette demande. Réessaie."

    def clear_session(self, conversation_key: str) -> None:
        """Drop a conversation (forgets its Claude session id)."""
        if self.registry.clear(conversation_key):
            ACTIVE_SESSIONS.set(self.registry.count())
