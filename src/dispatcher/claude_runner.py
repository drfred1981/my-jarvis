"""Interface with Claude Code CLI to process messages."""

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass

from services import get_active_services, get_active_mcp_config, get_allowed_tools_string

logger = logging.getLogger(__name__)

# Working directory where CLAUDE.md and MCP settings live
JARVIS_PROJECT_DIR = os.environ.get(
    "JARVIS_PROJECT_DIR", "/home/jarvis/app"
)

# MCP config file path (base config, will be filtered at runtime)
MCP_CONFIG = os.path.join(JARVIS_PROJECT_DIR, "mcp.json")

# Max budget per request (USD)
MAX_BUDGET = os.environ.get("JARVIS_MAX_BUDGET", "1.00")

# Max agentic turns per request
MAX_TURNS = os.environ.get("JARVIS_MAX_TURNS", "10")


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
        return self.sessions[session_id]

    def _get_mcp_config_path(self) -> str | None:
        """Generate a filtered mcp.json with only active services."""
        if not os.path.isfile(MCP_CONFIG):
            return None

        active_config = get_active_mcp_config(MCP_CONFIG)
        if not active_config.get("mcpServers"):
            logger.warning("No MCP services configured, Claude will run without tools")
            return None

        # Write filtered config to a temp file
        if self._runtime_mcp_config and os.path.isfile(self._runtime_mcp_config):
            os.unlink(self._runtime_mcp_config)

        fd, path = tempfile.mkstemp(suffix=".json", prefix="jarvis-mcp-")
        with os.fdopen(fd, "w") as f:
            json.dump(active_config, f, indent=2)
        self._runtime_mcp_config = path
        return path

    async def send_message(self, session_id: str, message: str) -> str:
        """Send a message to Claude Code and return the response."""
        async with self._lock:
            session = self._get_or_create_session(session_id)

        # Detect active services
        active_services = get_active_services()

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
                proc.communicate(), timeout=300
            )

            stderr_text = stderr.decode().strip()
            if stderr_text:
                logger.debug("Claude Code stderr: %s", stderr_text)

            if proc.returncode != 0:
                logger.error("Claude Code error (rc=%d): %s", proc.returncode, stderr_text)
                return f"Erreur Claude Code: {stderr_text}"

            output = stdout.decode().strip()

            try:
                result = json.loads(output)
                response_text = result.get("result", output)

                # Capture session ID for conversation continuity
                claude_sid = result.get("session_id")
                if claude_sid:
                    async with self._lock:
                        session.claude_session_id = claude_sid

            except json.JSONDecodeError:
                response_text = output

            return response_text

        except asyncio.TimeoutError:
            logger.error("Claude Code timeout for session %s", session_id)
            return "Timeout: Claude Code n'a pas répondu dans les 5 minutes."
        except Exception as e:
            logger.error("Claude Code exception: %s", e)
            return f"Erreur interne: {e}"

    def clear_session(self, session_id: str) -> None:
        """Clear a conversation session."""
        self.sessions.pop(session_id, None)
