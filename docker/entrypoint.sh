#!/bin/bash
set -e

echo "=== Jarvis starting ==="

# Seed Claude config files to /home/jarvis on first boot
# (only copies if files don't already exist on the persistent volume)
SEED_DIR="/opt/jarvis/seed"
HOME_DIR="/home/jarvis"

# CLAUDE.md and mcp.json are CONFIG (source of truth = image): merge the seed
# INTO the runtime file at every boot so redeploys apply doctrine + new MCP
# servers, while preserving runtime/operator-only additions.
#   - mcp.json : union of mcpServers (seed wins per key, volume-only kept)
#   - CLAUDE.md: section merge by '## ' (seed sections win, volume-only kept)
if [ -f "$SEED_DIR/CLAUDE.md" ]; then
    echo "Merging CLAUDE.md from seed"
    python3 /opt/jarvis/seed_merge.py "$SEED_DIR/CLAUDE.md" "$HOME_DIR/CLAUDE.md" md
fi
if [ -f "$SEED_DIR/mcp.json" ]; then
    echo "Merging mcp.json from seed"
    python3 /opt/jarvis/seed_merge.py "$SEED_DIR/mcp.json" "$HOME_DIR/mcp.json" json
fi

if [ ! -d "$HOME_DIR/.claude" ] && [ -d "$SEED_DIR/.claude" ]; then
    echo "Seeding .claude/ to $HOME_DIR/"
    cp -r "$SEED_DIR/.claude" "$HOME_DIR/.claude"
fi

# Sync memory files from seed (new files only, never overwrite runtime changes)
MEMORY_SEED="$SEED_DIR/memory"
MEMORY_DIR="$HOME_DIR/.claude/projects/-home-jarvis/memory"
if [ -d "$MEMORY_SEED" ]; then
    mkdir -p "$MEMORY_DIR"
    for f in "$MEMORY_SEED"/*.md; do
        [ -f "$f" ] || continue
        basename="$(basename "$f")"
        if [ ! -f "$MEMORY_DIR/$basename" ]; then
            echo "Seeding memory/$basename"
            cp "$f" "$MEMORY_DIR/$basename"
        fi
    done
fi

# Skills are read as two layers (figé/amendment), NOT seeded onto the volume:
#   - repo (frozen)   : $SEED_DIR/skills (image, read-only) — source of truth, refreshed
#                       every deploy, wins on name collision. Read in place; never copied.
#   - runtime (amend) : $JARVIS_SKILLS_DIR (volume) — where create_skill writes; survives
#                       restarts, layered on top, can never shadow a repo skill.
# We only ensure the runtime dir exists so create_skill has somewhere to write.
mkdir -p "${JARVIS_SKILLS_DIR:-$HOME_DIR/skills}"

# Nettoie les lock files git orphelins d'un run précédent (index.lock, config.lock…)
# Le sandbox Claude bloque leur suppression depuis l'intérieur d'une session active,
# donc on le fait ici au démarrage, avant que le dispatcher ne lance quoi que ce soit.
find "${HOME_DIR}/git-cache" -name "*.lock" -delete 2>/dev/null || true

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
