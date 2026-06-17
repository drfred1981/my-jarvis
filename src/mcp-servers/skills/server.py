"""MCP Server for skills — the agent's competency self-improvement surface.

Skills are Markdown procedures (hot-reloaded each turn). This server lets the
agent:
  - see its full skill catalog (`list_skills`, `read_skill`);
  - acquire a missing competency by authoring one (`create_skill`) — instant;
  - give a specific conversation its own competencies by attaching skills to it
    (`attach_skill` / `detach_skill` / `list_conversation_skills`).

All skills are globally available; attaching simply surfaces a skill's full
content in one conversation's injected context (managed by the dispatcher).

This module is thin: it wires MCP tools to `catalog` and `attachments`.

Env: JARVIS_SKILLS_DIR (default /home/jarvis/skills),
     JARVIS_MEMORY_DIR (default /home/jarvis/memory) for attachments.
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

import attachments
import catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("skills")


def _j(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def list_skills() -> str:
    """List all available skills (name, description, tools) — the global catalog."""
    return _j({"skills": catalog.list_skills()})


@mcp.tool()
def read_skill(name: str) -> str:
    """Read a skill's full SKILL.md content."""
    return _j(catalog.read_skill(name))


@mcp.tool()
def create_skill(name: str, description: str, content: str, tools: str = "") -> str:
    """Author a new skill (or update one) — use this when you lack a competency
    for the situation at hand. `name` kebab-case; `description` is the one-line
    relevance hint; `content` the Markdown procedure; `tools` an optional
    comma-separated list. Hot-reloaded immediately."""
    return _j(catalog.create_skill(name, description, content, tools))


@mcp.tool()
def attach_skill(conversation_key: str, name: str) -> str:
    """Attach a skill to a conversation so it becomes one of that conversation's
    own competencies (its full content is injected there). The conversation key
    is shown in the injected context header (e.g. 'discord:dm:42')."""
    return _j(attachments.attach(conversation_key, name))


@mcp.tool()
def detach_skill(conversation_key: str, name: str) -> str:
    """Remove a skill from a conversation's attached competencies."""
    return _j(attachments.detach(conversation_key, name))


@mcp.tool()
def list_conversation_skills(conversation_key: str) -> str:
    """List the skills currently attached to a conversation."""
    return _j(attachments.list_for(conversation_key))


if __name__ == "__main__":
    mcp.run()
