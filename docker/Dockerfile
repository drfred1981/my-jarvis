FROM node:22-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    ca-certificates \
    gnupg \
    lsb-release \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# --- Java JDK 21 ---
RUN wget -qO- https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /usr/share/keyrings/adoptium.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/adoptium.list \
    && apt-get update && apt-get install -y --no-install-recommends temurin-21-jdk \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME="/usr/lib/jvm/temurin-21-jdk-amd64"

# --- Maven ---
ARG MAVEN_VERSION=3.9.9
RUN wget -qO- "https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
    | tar xz -C /opt \
    && ln -s /opt/apache-maven-${MAVEN_VERSION}/bin/mvn /usr/local/bin/mvn

# --- Docker CLI (for Docker-in-Docker) ---
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# --- kubectl ---
RUN curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    -o /usr/local/bin/kubectl && chmod +x /usr/local/bin/kubectl

# --- helm ---
RUN curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# --- flux CLI ---
RUN curl -fsSL https://fluxcd.io/install.sh | bash

# --- mise (runtime version manager) ---
RUN curl -fsSL https://mise.jdx.dev/install.sh | MISE_INSTALL_PATH=/usr/local/bin/mise bash

# --- sops (secrets encryption) ---
ARG SOPS_VERSION=3.9.4
RUN curl -fsSL "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
    -o /usr/local/bin/sops && chmod +x /usr/local/bin/sops

# --- task (task runner / Taskfile) ---
RUN sh -c "$(curl -fsSL https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin

# --- Claude Code ---
RUN npm install -g @anthropic-ai/claude-code

# Create app user and add to docker group
RUN groupadd -f docker && useradd -m -s /bin/bash -G docker jarvis

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

# Copy project files (overridden by volume mount in dev)
COPY --chown=jarvis:jarvis CLAUDE.md mcp.json requirements.txt ./
COPY --chown=jarvis:jarvis src/ src/
COPY --chown=jarvis:jarvis .claude/ .claude/

# Fix permissions
RUN chown -R jarvis:jarvis /home/jarvis

USER jarvis

# Non-secret defaults only (secrets are injected at runtime via .env / k8s secrets)
ENV JARVIS_PROJECT_DIR="/home/jarvis/app"

EXPOSE 8080

ENTRYPOINT ["entrypoint.sh"]
