# Jarvis

Assistant personnel propulsé par Claude Code, avec accès à un cluster Kubernetes, Home Assistant, et une dizaine de services homelab.

## Architecture

```
Discord / Web UI / Synology Chat
        |
  Dispatcher (FastAPI :8080)
        |
  Claude Code CLI (10 MCP servers)
        |
  K8s / FluxCD / Git / HA / Grafana / Planka / Miniflux / Immich / Karakeep / Music Assistant
```

- **Dispatcher** : FastAPI qui reçoit les messages, invoque Claude Code, retourne les réponses
- **MCP Servers** : chaque service est exposé via un serveur MCP (Model Context Protocol) que Claude Code utilise comme tools
- **Monitoring proactif** : checks périodiques du cluster, HA et FluxCD avec alertes automatiques sur tous les canaux

## Prérequis

- Docker (avec Docker Compose)
- Un cluster Kubernetes accessible (kubeconfig)
- Claude Code installé et authentifié (`claude login`)

## Installation

### 1. Cloner le repo

```bash
git clone https://github.com/drfred1981/my-jarvis.git
cd my-jarvis
```

### 2. Authentifier Claude Code

Jarvis utilise Claude Code directement (pas de clé API). Il faut être authentifié sur la machine hôte :

```bash
# Se connecter à Claude Code (une seule fois)
claude login
```

La config `~/.claude/` est montée dans le container automatiquement.

### 3. Créer le fichier `.env`

```bash
cp .env.example .env
```

Ouvrir `.env` et remplir les valeurs (tokens des services).

### 4. Récupérer les tokens et clés API

| Service | Comment obtenir le token |
|---------|------------------------|
| **Discord** | Voir section [Créer le bot Discord](#créer-le-bot-discord) ci-dessous |
| **Home Assistant** | Profil utilisateur HA > Tokens de longue durée > Créer un token |
| **GitHub** | https://github.com/settings/tokens > Fine-grained token avec accès aux repos |
| **Grafana** | Administration > Service Accounts > Add token |
| **Planka** | Utiliser un compte utilisateur existant (email + mot de passe) |
| **Miniflux** | Settings > API Keys > Create a new API key |
| **Immich** | Administration > API Keys > New API Key |
| **Karakeep** | Settings > API Keys |
| **Music Assistant** | Pas de token requis |

### 5. Vérifier le kubeconfig

Jarvis a besoin d'accéder au cluster Kubernetes. Vérifier que le kubeconfig est disponible :

```bash
# Tester l'accès
kubectl get nodes

# Le chemin par défaut est ~/.kube/config
# Sinon, définir la variable KUBECONFIG dans le .env ou l'exporter
export KUBECONFIG=/chemin/vers/kubeconfig
```

### 6. Adapter les URLs des services

Dans `.env`, remplacer les URLs par défaut par les URLs réelles de vos services dans le cluster. Exemples :

```bash
HA_URL=http://home-assistant.home.svc.cluster.local:8123
GRAFANA_URL=http://grafana.monitoring.svc.cluster.local:3000
PROMETHEUS_URL=http://prometheus-server.monitoring.svc.cluster.local:9090
```

Les URLs dépendent de vos namespaces et noms de services Kubernetes.

### 7. Configurer les repos Git

Lister vos repos dans la variable `GIT_REPOS` au format JSON :

```bash
GIT_REPOS={"infra":"https://github.com/user/home-k8s-infra.git","apps":"https://github.com/user/home-k8s-apps.git"}
```

### 8. Builder et lancer

```bash
cd docker
docker compose up --build
```

Jarvis est accessible sur http://localhost:8080.

## Créer le bot Discord

1. Aller sur https://discord.com/developers/applications
2. **New Application** > nommer "Jarvis"
3. Onglet **Bot** :
   - Cliquer **Reset Token** et copier le token > mettre dans `DISCORD_BOT_TOKEN`
   - Activer **Message Content Intent** dans Privileged Gateway Intents
4. Onglet **OAuth2** > URL Generator :
   - Scopes : `bot`
   - Bot Permissions : `Send Messages`, `Read Message History`, `Read Messages/View Channels`
   - Copier l'URL et l'ouvrir pour inviter le bot dans votre serveur
5. (Optionnel) Restreindre à certains canaux en mettant les IDs dans `DISCORD_CHANNEL_IDS`

Pour obtenir un channel ID : activer le mode développeur dans Discord (Paramètres > Avancé) puis clic droit sur un canal > Copier l'identifiant.

## Utilisation

### Web UI
Ouvrir http://localhost:8080 et discuter avec Jarvis.

### Discord
Mentionner le bot (`@Jarvis`) ou lui envoyer un DM.

### Synology Chat
Configurer un webhook sortant vers `http://<jarvis-ip>:8080/api/webhooks/synology`.

### API REST

```bash
# Envoyer un message
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Quel est l état du cluster ?", "session_id": "mon-session"}'

# Health check
curl http://localhost:8080/api/health
```

## MCP Servers

| Server | Outils |
|--------|--------|
| `kubernetes` | list_pods, get_pod_logs, describe_pod, list_deployments, list_services, get_nodes_status, get_cluster_health |
| `fluxcd` | list_git_repositories, list_kustomizations, list_helm_releases, get_reconciliation_status |
| `git` | list_repos, browse, read_file, search_files, git_log, git_diff, list_branches |
| `homeassistant` | list_entities, get_entity_state, call_service, list_automations, get_history, fire_event, get_config |
| `grafana-prometheus` | prometheus_query, prometheus_query_range, prometheus_alerts, prometheus_rules, prometheus_targets, grafana_list_dashboards, grafana_get_dashboard, grafana_alerts |
| `planka` | list_projects, get_project, get_board, get_card, create_card, move_card, add_comment |
| `miniflux` | list_feeds, list_categories, get_unread_entries, get_entry, search_entries, mark_as_read, toggle_star, get_feed_counters, refresh_all_feeds |
| `immich` | get_server_stats, get_server_info, search_assets, search_metadata, list_albums, get_album, get_asset_info, list_people, get_timeline_stats |
| `karakeep` | list_bookmarks, search_bookmarks, get_bookmark, create_bookmark, list_tags, list_lists, get_list_bookmarks |
| `music-assistant` | list_players, get_player, search, list_artists, list_albums, list_playlists, play_media, player_command, set_volume, get_queue |

## Outils dans l'image Docker

| Outil | Version |
|-------|---------|
| Node.js + npm | 22 |
| Java JDK | 21 (Temurin) |
| Maven | 3.9.9 |
| Python | 3.x |
| kubectl | latest |
| helm | latest |
| flux CLI | latest |
| Docker CLI | latest (DinD) |
| mise | latest |
| sops | 3.9.4 |
| task | latest |
| Claude Code | latest |

## Monitoring proactif

Jarvis effectue des checks automatiques en arrière-plan :

| Check | Intervalle | Ce qu'il vérifie |
|-------|-----------|-----------------|
| Cluster health | 15 min | Pods en erreur, restarts, nodes en pression, alertes Prometheus |
| Home Assistant | 30 min | Entités unavailable, automations en erreur |
| FluxCD | 10 min | Réconciliations en échec |

Les alertes sont envoyées sur tous les canaux actifs (Discord, Web UI, Synology Chat).
Désactiver avec `JARVIS_MONITORING=false` dans `.env`.

## Structure du projet

```
my-jarvis/
├── .claude/settings.json          # Config MCP servers
├── .env.example                   # Template des variables d'environnement
├── .github/workflows/             # CI/CD
├── CLAUDE.md                      # System prompt Jarvis
├── mcp.json                       # Config MCP pour Claude Code CLI
├── requirements.txt               # Deps Python
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── entrypoint.sh
└── src/
    ├── dispatcher/                # FastAPI + channels + monitoring
    │   ├── main.py
    │   ├── claude_runner.py
    │   ├── monitor.py
    │   ├── notifier.py
    │   └── channels/
    ├── mcp-servers/               # 10 MCP servers
    │   ├── kubernetes/
    │   ├── fluxcd/
    │   ├── git/
    │   ├── homeassistant/
    │   ├── grafana-prometheus/
    │   ├── planka/
    │   ├── miniflux/
    │   ├── immich/
    │   ├── karakeep/
    │   └── music-assistant/
    └── web-ui/                    # Interface chat
```
