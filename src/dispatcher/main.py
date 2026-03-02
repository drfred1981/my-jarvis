"""Jarvis - Main dispatcher server.

Central FastAPI application that receives messages from all channels
(Discord, Web UI, Synology Chat) and routes them through Claude Code.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import make_asgi_app
from pydantic import BaseModel

# Ensure dispatcher package is importable
sys.path.insert(0, os.path.dirname(__file__))

from claude_runner import ClaudeRunner
from channels.discord_bot import DiscordBot
from channels.web_socket import ConnectionManager
from metrics import (
    MESSAGES_TOTAL,
    MESSAGE_DURATION_SECONDS,
    MONITOR_ALERTS_ACKNOWLEDGED_TOTAL,
    SERVICES_AVAILABLE,
    WEBSOCKET_CONNECTIONS,
)
from monitor import Monitor
from notifier import Notifier
from services import get_available_services, log_service_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Jarvis", version="0.1.0")
claude = ClaudeRunner()
ws_manager = ConnectionManager()
notifier = Notifier()
monitor = Monitor(claude_runner=claude, notifier=notifier)
discord_bot: DiscordBot | None = None

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Serve web UI static files
WEB_UI_DIR = os.path.join(os.path.dirname(__file__), "..", "web-ui")
if os.path.isdir(WEB_UI_DIR):
    app.mount("/static", StaticFiles(directory=WEB_UI_DIR), name="static")


# --- REST API ---

class MessageRequest(BaseModel):
    message: str
    session_id: str = "default"


class MessageResponse(BaseModel):
    response: str
    session_id: str


@app.get("/")
async def root():
    """Serve the web UI with inline CSS/JS (no caching issues)."""
    css_path = os.path.join(WEB_UI_DIR, "style.css")
    js_path = os.path.join(WEB_UI_DIR, "app.js")
    if not os.path.isfile(css_path):
        return {"status": "Jarvis is running", "version": "0.1.0"}

    with open(css_path) as f:
        css = f.read()
    with open(js_path) as f:
        js = f.read()

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jarvis</title>
<style>{css}</style>
</head>
<body>
<div id="app">
  <header>
    <h1>Jarvis</h1>
    <span class="status" id="status">Connexion...</span>
  </header>
  <main id="chat">
    <div id="messages"></div>
  </main>
  <footer>
    <form id="input-form">
      <textarea id="input" placeholder="Parle à Jarvis..." rows="1" autofocus></textarea>
      <button type="submit" id="send-btn">Envoyer</button>
    </form>
  </footer>
</div>
<script>{js}</script>
</body>
</html>"""
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.post("/api/chat", response_model=MessageResponse)
async def chat(req: MessageRequest):
    """Send a message to Jarvis and get a response."""
    logger.info("REST /api/chat (session=%s): %s", req.session_id, req.message[:100])
    with MESSAGE_DURATION_SECONDS.labels(channel="rest").time():
        response = await claude.send_message(req.session_id, req.message)
    MESSAGES_TOTAL.labels(channel="rest", status="success").inc()
    logger.info("REST response (session=%s): %s", req.session_id, response[:100])
    return MessageResponse(response=response, session_id=req.session_id)


@app.post("/api/sessions/{session_id}/clear")
async def clear_session(session_id: str):
    """Clear a conversation session."""
    claude.clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}


@app.get("/api/alerts")
async def list_alerts():
    """List active monitoring alerts and their status."""
    alerts = {}
    for name, state in monitor._alert_states.items():
        alerts[name] = {
            "paused": not state.acknowledged,
            "acknowledged": state.acknowledged,
            "sent_at": state.sent_at.isoformat() if state.sent_at else None,
        }
    return {"alerts": alerts}


@app.post("/api/alerts/{check_name}/ack")
async def acknowledge_alert(check_name: str):
    """Acknowledge a monitoring alert to resume the check."""
    if monitor.acknowledge_alert(check_name):
        MONITOR_ALERTS_ACKNOWLEDGED_TOTAL.labels(check=check_name).inc()
        return {"status": "acknowledged", "check": check_name}
    return {"status": "not_found", "check": check_name}


@app.get("/api/health")
async def health():
    services = get_available_services()
    active = [name for name, ok in services.items() if ok]
    inactive = [name for name, ok in services.items() if not ok]
    return {
        "status": "ok",
        "services": {
            "active": active,
            "inactive": inactive,
        },
    }


# --- WebSocket for push notifications only ---

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket for push notifications (monitoring alerts, etc.).

    Messages should be sent via POST /api/chat, not WebSocket.
    This endpoint only keeps the connection alive and pushes server events.
    """
    await ws_manager.connect(websocket, session_id)
    WEBSOCKET_CONNECTIONS.inc()
    try:
        while True:
            # Keep connection alive by reading (ignore any incoming text)
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)
        WEBSOCKET_CONNECTIONS.dec()


# --- Synology Chat webhook ---

@app.post("/api/webhooks/synology")
async def synology_webhook(payload: dict):
    """Handle incoming Synology Chat webhooks."""
    # Synology Chat sends: {"token": "...", "user_id": ..., "username": "...", "text": "..."}
    text = payload.get("text", "")
    user_id = str(payload.get("user_id", "synology"))
    session_id = f"synology-{user_id}"

    with MESSAGE_DURATION_SECONDS.labels(channel="synology").time():
        response = await claude.send_message(session_id, text)
    MESSAGES_TOTAL.labels(channel="synology", status="success").inc()

    # Synology Chat expects: {"text": "response"}
    return {"text": response}


# --- Git repo pre-clone (runs in dispatcher, not in MCP server) ---

def _preclone_git_repos():
    """Pre-clone git repos at dispatcher startup.

    MCP servers are short-lived subprocesses of `claude -p`, so they can't
    reliably clone repos in background threads. We do it here in the
    long-running dispatcher process instead, writing to the same cache
    directory the MCP server expects.
    """
    repos_json = os.getenv("GIT_REPOS", "")
    if not repos_json:
        logger.info("Git pre-clone: GIT_REPOS not set, skipping")
        return

    try:
        repos = json.loads(repos_json)
    except json.JSONDecodeError:
        logger.error("Git pre-clone: invalid GIT_REPOS JSON: %s", repos_json)
        return

    project_dir = os.environ.get("JARVIS_PROJECT_DIR", "/home/jarvis")
    cache_dir = os.path.join(project_dir, "git-cache")
    github_token = os.getenv("GITHUB_TOKEN", "")

    os.makedirs(cache_dir, exist_ok=True)
    logger.info("Git pre-clone: %d repos to %s", len(repos), cache_dir)

    for name, url in repos.items():
        repo_dir = os.path.join(cache_dir, name)
        auth_url = url
        if github_token and "github.com" in url:
            auth_url = url.replace("https://", f"https://{github_token}@")

        try:
            if os.path.isdir(os.path.join(repo_dir, ".git")):
                logger.info("Git pre-clone: %s already cached, pulling...", name)
                result = subprocess.run(
                    ["git", "-C", repo_dir, "fetch", "--all", "--prune"],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode != 0:
                    logger.warning("Git fetch failed for %s: %s", name, result.stderr.strip())
                else:
                    subprocess.run(
                        ["git", "-C", repo_dir, "pull", "--rebase"],
                        capture_output=True, text=True, timeout=60,
                    )
                    logger.info("Git pre-clone: %s updated", name)
            else:
                # Clean up partial clone dir
                if os.path.exists(repo_dir):
                    shutil.rmtree(repo_dir, ignore_errors=True)
                    logger.info("Git pre-clone: removed partial dir for %s", name)
                logger.info("Git pre-clone: cloning %s ...", name)
                result = subprocess.run(
                    ["git", "clone", auth_url, repo_dir],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    logger.error("Git clone failed for %s: %s", name, result.stderr.strip())
                else:
                    logger.info("Git pre-clone: %s cloned OK", name)
        except Exception as e:
            logger.error("Git pre-clone error for %s: %s", name, e)

    logger.info("Git pre-clone: done")


# --- Startup / Shutdown ---

@app.on_event("startup")
async def startup():
    global discord_bot

    # Log service availability and set metrics
    log_service_status()
    for name, available in get_available_services().items():
        SERVICES_AVAILABLE.labels(service=name).set(1 if available else 0)

    # Pre-clone git repos in background thread (non-blocking)
    threading.Thread(target=_preclone_git_repos, daemon=True, name="git-preclone").start()

    # Channels - Discord
    discord_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if discord_token:
        try:
            discord_bot = DiscordBot(claude_runner=claude, token=discord_token)
            await discord_bot.start_background()
            notifier.set_discord_bot(discord_bot)
            logger.info("Channel enabled: Discord")
        except Exception as e:
            logger.warning("Channel failed: Discord (%s)", e)
            discord_bot = None
    else:
        logger.info("Channel disabled: Discord (DISCORD_BOT_TOKEN not set)")

    notifier.set_ws_manager(ws_manager)

    synology_url = os.getenv("SYNOLOGY_CHAT_WEBHOOK_URL", "").strip()
    if synology_url:
        logger.info("Channel enabled: Synology Chat (webhook)")
    else:
        logger.info("Channel disabled: Synology Chat (SYNOLOGY_CHAT_WEBHOOK_URL not set)")

    logger.info("Channel enabled: Web UI (http://0.0.0.0:8080)")

    # Proactive monitoring
    try:
        await monitor.start()
    except Exception as e:
        logger.warning("Monitoring failed to start: %s", e)

    logger.info("Jarvis dispatcher ready")


@app.on_event("shutdown")
async def shutdown():
    await monitor.stop()
    if discord_bot:
        try:
            await discord_bot.close()
        except Exception:
            pass
    logger.info("Jarvis dispatcher stopped")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=os.getenv("ENV", "production") == "development",
    )
