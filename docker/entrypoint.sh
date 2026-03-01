#!/bin/bash
set -e

echo "=== Jarvis starting ==="

# Seed Claude config files to /home/jarvis on first boot
# (only copies if files don't already exist on the persistent volume)
SEED_DIR="/opt/jarvis/seed"
HOME_DIR="/home/jarvis"

for f in CLAUDE.md mcp.json; do
    if [ ! -f "$HOME_DIR/$f" ] && [ -f "$SEED_DIR/$f" ]; then
        echo "Seeding $f to $HOME_DIR/"
        cp "$SEED_DIR/$f" "$HOME_DIR/$f"
    fi
done

if [ ! -d "$HOME_DIR/.claude" ] && [ -d "$SEED_DIR/.claude" ]; then
    echo "Seeding .claude/ to $HOME_DIR/"
    cp -r "$SEED_DIR/.claude" "$HOME_DIR/.claude"
fi

# Install/update Python dependencies
if [ -f /opt/jarvis/app/requirements.txt ]; then
    echo "Installing Python dependencies..."
    pip install --quiet --no-cache-dir -r /opt/jarvis/app/requirements.txt
fi

# Verify Claude Code is available
echo "Claude Code $(claude --version 2>/dev/null || echo 'not found')"

echo "=== Starting dispatcher on :8080 ==="
cd /opt/jarvis/app
exec python3 src/dispatcher/main.py
