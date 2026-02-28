#!/bin/bash
set -e

echo "=== Jarvis starting ==="

# Install/update Python dependencies from mounted volume
if [ -f /home/jarvis/app/requirements.txt ]; then
    echo "Installing Python dependencies..."
    pip install --quiet --no-cache-dir -r /home/jarvis/app/requirements.txt
fi

# Ensure .claude directory exists in the mounted volume
mkdir -p /home/jarvis/app/.claude

# Verify Claude Code is available
echo "Claude Code $(claude --version 2>/dev/null || echo 'not found')"

echo "=== Starting dispatcher on :8080 ==="
exec python3 src/dispatcher/main.py
