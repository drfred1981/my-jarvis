# Jarvis skills

This directory holds **Claude Code skills** that Jarvis can invoke during a conversation. Each subdirectory is one skill, with a `SKILL.md` describing when to use it and what to do.

Claude Code auto-discovers skills here when this path is configured in `~/.claude/settings.json` (handled by the Helm chart — see `skillsPath` in the deployment).

## Layout

```
skills/
  README.md
  <skill-name>/
    SKILL.md          # frontmatter + body; the trigger and the procedure
    <scripts...>      # optional helper scripts
```

## Conventions

- **One purpose per skill**. If you find yourself writing "and also..." in a SKILL.md, split it.
- **Frontmatter is mandatory**: `name`, `description` (used by Claude to decide *when* to load it), and optional `tools`.
- The `description` is the trigger — make it specific (verbs + concrete situation), not a generic noun.
- Skills can call any of the MCP servers configured in `mcp.json` (memory, git, planka, kubernetes, …).

## Adding a skill

1. `mkdir skills/<skill-name>`
2. Write `skills/<skill-name>/SKILL.md` with frontmatter + body.
3. Commit. The next pod restart picks it up (the `skills/` directory is baked into the container image, or — if a writable PVC mount is preferred — bind-mounted from the NFS PVC at `/home/jarvis/skills` and merged with the image's `skills/`).
