"""Interface with Claude Code CLI to process messages."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass

from metrics import ACTIVE_SESSIONS
from services import get_active_services, get_active_mcp_config, get_allowed_tools_string

logger = logging.getLogger(__name__)

# Working directory where CLAUDE.md and MCP settings live
JARVIS_PROJECT_DIR = os.environ.get(
    "JARVIS_PROJECT_DIR", "/home/jarvis"
)

# MCP config file path (base config, will be filtered at runtime)
MCP_CONFIG = os.path.join(JARVIS_PROJECT_DIR, "mcp.json")

# Max budget per request (USD)
MAX_BUDGET = os.environ.get("JARVIS_MAX_BUDGET", "1.00")

# Max agentic turns per request
MAX_TURNS = os.environ.get("JARVIS_MAX_TURNS", "25")

# Timeout per request (seconds)
TIMEOUT = int(os.environ.get("JARVIS_TIMEOUT", "300"))


@dataclass
class ConversationSession:
    """Tracks a conversation session with Claude Code."""
    session_id: str
    claude_session_id: str | None = None


class ClaudeRunner:
    """Runs Claude Code CLI commands and manages conversation sessions."""

    def __init__(self):
        self.sessions: dict[str, ConversationSession] = {}
        self._lock = asyncio.Lock()
        self._runtime_mcp_config: str | None = None

    def _get_or_create_session(self, session_id: str) -> ConversationSession:
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationSession(session_id=session_id)
            ACTIVE_SESSIONS.inc()
        return self.sessions[session_id]

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

    async def send_message(self, session_id: str, message: str) -> str:
        """Send a message to Claude Code and return the response."""
        logger.info("Processing message for session %s: %s", session_id, message[:100])

        async with self._lock:
            session = self._get_or_create_session(session_id)

        # Detect active services
        active_services = get_active_services()
        logger.info("Active MCP services: %s", active_services or "none")

        cmd = [
            "claude",
            "-p", message,
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
        if session.claude_session_id:
            cmd.extend(["--resume", session.claude_session_id])

        logger.info("Running: %s (cwd=%s)", " ".join(cmd[:6]) + " ...", JARVIS_PROJECT_DIR)

        env = os.environ.copy()

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

            # Capture session ID for conversation continuity
            try:
                result = json.loads(output)
                claude_sid = result.get("session_id")
                if claude_sid:
                    async with self._lock:
                        session.claude_session_id = claude_sid
            except (json.JSONDecodeError, AttributeError):
                pass

            return response_text

        except asyncio.TimeoutError:
            logger.error("Claude Code timeout for session %s", session_id)
            return f"Timeout: Claude Code n'a pas répondu dans les {TIMEOUT} secondes."
        except Exception as e:
            logger.error("Claude Code exception: %s", e)
            return f"Erreur interne: {e}"

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

    def clear_session(self, session_id: str) -> None:
        """Clear a conversation session."""
        if self.sessions.pop(session_id, None) is not None:
            ACTIVE_SESSIONS.dec()
