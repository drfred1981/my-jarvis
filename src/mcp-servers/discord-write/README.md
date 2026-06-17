# discord-write MCP

Lets the agent **create Discord threads** and **post messages** — primarily to give
each managed repo its own dedicated thread (see the `repo-workflow` skill).

Uses the Discord **REST API** directly (no gateway), since MCP servers are short-lived
subprocesses. Auth: the bot token (`Authorization: Bot <token>`).

## Modules

| File | Role |
|------|------|
| `server.py` | Thin MCP wiring (`@mcp.tool`) |
| `api.py`    | Discord REST client (create thread, post message, list threads) |

## Tools

- `create_thread(channel_id, name, private=False, auto_archive_minutes=1440)` →
  new `thread_id` + `conversation_key` (`discord:thread:<id>`).
  `auto_archive_minutes` ∈ {60, 1440, 4320, 10080}.
- `post_message(channel_id, content)` → post to a channel or thread (chunked to 2000).
- `list_active_threads(guild_id)` → active threads (find an existing repo thread first).

## Env vars

| Var | Required | Purpose |
|-----|----------|---------|
| `DISCORD_BOT_TOKEN` | yes | same token as the dispatcher bot |

The bot must be in the target guild with **Manage Threads** and **Send Messages**
permissions. Once a thread exists, the dispatcher's Discord bot routes its messages as
`discord:thread:<id>` (multi-user, invoke-only) automatically.
