# discord-write MCP

Lets the agent **create Discord threads** and **post messages** — primarily to give
each managed repo its own dedicated thread (see the `repo-workflow` skill).

Uses the Discord **REST API** directly (no gateway), since MCP servers are short-lived
subprocesses. Auth: the bot token (`Authorization: Bot <token>`).

## Modules

| File | Role |
|------|------|
| `server.py` | Thin MCP wiring (`@mcp.tool`) |
| `api.py`    | Discord REST client (create thread, post message, post file, list threads) |

## Tools

- `create_thread(channel_id, name, private=False, auto_archive_minutes=1440)` →
  new `thread_id` + `conversation_key` (`discord:thread:<id>`).
  `auto_archive_minutes` ∈ {60, 1440, 4320, 10080}.
- `post_message(channel_id, content)` → post to a channel or thread (chunked to 2000).
- `post_file(channel_id, file_path, content="")` → upload a local file as an attachment
  (multipart), with optional text. Write the artefact first (e.g. under `/home/jarvis`),
  then pass its path. Max 25 MiB (`DISCORD_MAX_UPLOAD_MB`). Returns the message id and the
  uploaded attachment URL(s).
- `list_active_threads(guild_id)` → active threads (find an existing repo thread first).

**Receiving files** is the dispatcher bot's job, not this MCP: when a Discord message
carries attachments, `channels/discord_bot.py` downloads them under
`JARVIS_DISCORD_INBOX/<message_id>/` and adds their local paths to the prompt, so Jarvis
can `Read`/analyze them.

## Env vars

| Var | Required | Purpose |
|-----|----------|---------|
| `DISCORD_BOT_TOKEN` | yes | same token as the dispatcher bot |
| `DISCORD_MAX_UPLOAD_MB` | no | upload size ceiling (default 25) |

The bot must be in the target guild with **Manage Threads**, **Send Messages** and
**Attach Files** permissions. Once a thread exists, the dispatcher's Discord bot routes
its messages as `discord:thread:<id>` (multi-user, invoke-only) automatically.
