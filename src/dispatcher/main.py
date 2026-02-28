"""Jarvis - Main dispatcher server.

Central FastAPI application that receives messages from all channels
(Discord, Web UI, Synology Chat) and routes them through Claude Code.
"""

import logging
import os
import sys

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure dispatcher package is importable
sys.path.insert(0, os.path.dirname(__file__))

from claude_runner import ClaudeRunner
from channels.discord_bot import DiscordBot
from channels.web_socket import ConnectionManager
from monitor import Monitor
from notifier import Notifier

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
    """Serve the web UI."""
    index_path = os.path.join(WEB_UI_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"status": "Jarvis is running", "version": "0.1.0"}


@app.post("/api/chat", response_model=MessageResponse)
async def chat(req: MessageRequest):
    """Send a message to Jarvis and get a response."""
    response = await claude.send_message(req.session_id, req.message)
    return MessageResponse(response=response, session_id=req.session_id)


@app.post("/api/sessions/{session_id}/clear")
async def clear_session(session_id: str):
    """Clear a conversation session."""
    claude.clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# --- WebSocket for real-time chat ---

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            response = await claude.send_message(session_id, data)
            await ws_manager.send_message(response, websocket)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)


# --- Synology Chat webhook ---

@app.post("/api/webhooks/synology")
async def synology_webhook(payload: dict):
    """Handle incoming Synology Chat webhooks."""
    # Synology Chat sends: {"token": "...", "user_id": ..., "username": "...", "text": "..."}
    text = payload.get("text", "")
    user_id = str(payload.get("user_id", "synology"))
    session_id = f"synology-{user_id}"

    response = await claude.send_message(session_id, text)

    # Synology Chat expects: {"text": "response"}
    return {"text": response}


# --- Startup / Shutdown ---

@app.on_event("startup")
async def startup():
    global discord_bot

    # Channels
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    if discord_token:
        discord_bot = DiscordBot(claude_runner=claude, token=discord_token)
        await discord_bot.start_background()
        notifier.set_discord_bot(discord_bot)
        logger.info("Channel enabled: Discord")
    else:
        logger.info("Channel disabled: Discord (DISCORD_BOT_TOKEN not set)")

    notifier.set_ws_manager(ws_manager)

    synology_url = os.getenv("SYNOLOGY_CHAT_WEBHOOK_URL")
    if synology_url:
        logger.info("Channel enabled: Synology Chat (webhook)")
    else:
        logger.info("Channel disabled: Synology Chat (SYNOLOGY_CHAT_WEBHOOK_URL not set)")

    logger.info("Channel enabled: Web UI (http://0.0.0.0:8080)")

    # Services
    for name, var in [
        ("Home Assistant", "HA_URL"),
        ("Prometheus", "PROMETHEUS_URL"),
        ("Grafana", "GRAFANA_URL"),
        ("FluxCD repo", "FLUX_REPO_URL"),
    ]:
        val = os.getenv(var)
        if val:
            logger.info("Service configured: %s (%s)", name, val)
        else:
            logger.info("Service not configured: %s (%s not set)", name, var)

    # Proactive monitoring
    await monitor.start()

    logger.info("Jarvis dispatcher ready")


@app.on_event("shutdown")
async def shutdown():
    await monitor.stop()
    if discord_bot:
        await discord_bot.close()
    logger.info("Jarvis dispatcher stopped")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=os.getenv("ENV", "production") == "development",
    )
