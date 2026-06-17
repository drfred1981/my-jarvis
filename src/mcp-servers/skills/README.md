# skills MCP

The agent's **competency self-improvement** surface. Skills are Markdown
procedures (`<JARVIS_SKILLS_DIR>/<name>/SKILL.md`, frontmatter `name` /
`description` / `tools`), hot-reloaded each agent turn.

Two scopes:
- **Global** — every skill in the library is listed (name + description) in the
  injected context of every user/introspection conversation. The agent always
  knows its full skill set.
- **Per-conversation** — a skill *attached* to a conversation has its full content
  injected in that conversation only, giving it its own competencies.

## Modules

| File | Role |
|------|------|
| `server.py`      | Thin MCP wiring (`@mcp.tool`) |
| `catalog.py`     | List / read / **create** SKILL.md (self-improvement) |
| `attachments.py` | Per-conversation attach / detach (NFS, shared with the injector) |

## Tools

- `list_skills()` → global catalog
- `read_skill(name)` → full content
- `create_skill(name, description, content, tools="")` → author a missing competency (instant)
- `attach_skill(conversation_key, name)` → give a conversation this competency
- `detach_skill(conversation_key, name)`
- `list_conversation_skills(conversation_key)`

The conversation key is shown in the injected context header (e.g. `discord:dm:42`).

## Where things live

- Skill library: `JARVIS_SKILLS_DIR` (default `/home/jarvis/skills`).
- Attachments: `<JARVIS_MEMORY_DIR>/skill-attachments/<key with ':'→'-'>.json`
  — read by the dispatcher injector (`src/dispatcher/context/skills.py`) to surface
  attached skills in context.

## Env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `JARVIS_SKILLS_DIR` | `/home/jarvis/skills` | skill library |
| `JARVIS_MEMORY_DIR` | `/home/jarvis/memory` | attachments root (shared NFS) |
