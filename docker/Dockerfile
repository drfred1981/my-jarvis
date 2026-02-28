FROM node:22-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    -o /usr/local/bin/kubectl && chmod +x /usr/local/bin/kubectl

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Create app user
RUN useradd -m -s /bin/bash jarvis

# Python virtual environment (persists even if workdir is mounted)
RUN python3 -m venv /home/jarvis/venv
ENV PATH="/home/jarvis/venv/bin:$PATH"

# Pre-install Python dependencies into the venv (updated at runtime by entrypoint)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Entrypoint script
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# Working directory = mount point for the project
WORKDIR /home/jarvis/app

# Fix permissions
RUN chown -R jarvis:jarvis /home/jarvis

USER jarvis

# Environment variables (overridden at runtime)
ENV ANTHROPIC_API_KEY=""
ENV DISCORD_BOT_TOKEN=""
ENV GITHUB_TOKEN=""
ENV HA_TOKEN=""
ENV HA_URL=""
ENV PROMETHEUS_URL=""
ENV GRAFANA_URL=""
ENV GRAFANA_TOKEN=""
ENV JARVIS_PROJECT_DIR="/home/jarvis/app"

EXPOSE 8080

ENTRYPOINT ["entrypoint.sh"]
