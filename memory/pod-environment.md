---
name: Environnement du pod Jarvis
description: Infos sur le pod K8s dans lequel tourne Jarvis (image, outils, repos, services accessibles)
type: reference
---

## Pod Jarvis

- **Pod** : `jarvis` (deployment `jarvis`, ReplicaSet pattern `jarvis-*`)
- **Hostname exemple** : `jarvis-7d7d97675c-v5vpg`
- **Image base** : Debian 12 (bookworm), kernel Talos
- **User** : `jarvis` (uid=1001, gid=1002), membre du groupe `docker`
- **Home** : `/home/jarvis`
- **Timezone** : `Europe/Paris`
- **App dir** : `/opt/jarvis/app` (code applicatif), `/opt/jarvis/venv` (virtualenv Python), `/opt/jarvis/seed` (données initiales)

## Runtimes & outils CLI

| Outil | Chemin |
|-------|--------|
| kubectl | /usr/local/bin/kubectl |
| helm | /usr/local/bin/helm |
| flux | /usr/local/bin/flux |
| docker | /usr/bin/docker (Docker-in-Docker) |
| java 21 | /usr/bin/java (Temurin 21) |
| node 22 | /usr/local/bin/node (v22.22.1) |
| npm | /usr/local/bin/npm |
| mise | /usr/local/bin/mise |
| sops | /usr/local/bin/sops |
| task | /usr/local/bin/task |
| git | /usr/bin/git |

Note : `maven` n'est pas dans le PATH (pas installé ou disponible via mise).

## Repos Git cachés localement

Répertoire : `/home/jarvis/git-cache/`
- `apps-in-k8s` — repo GitOps principal (home-automation)
- `my-jarvis` — code source de Jarvis lui-même
- `home-k8s-metadata` — métadonnées cluster

## Variables d'environnement clés (non-secrets)

| Variable | Valeur / Usage |
|----------|---------------|
| JARVIS_MAX_BUDGET | 20 ($ par conversation) |
| JARVIS_MAX_TURNS | 200 |
| JARVIS_TIMEOUT | 1200s |
| JARVIS_MONITORING | true |
| GIT_REPOS | apps-in-k8s, jarvis, home-k8s-metadata, paperdms, melimath |
| REPO_PATH | /repo/home-automation |

## URLs des services internes (in-cluster)

| Service | URL interne |
|---------|-------------|
| Home Assistant | http://home-assistant.home.svc.cluster.local:8123 |
| Planka | http://planka.services-it.svc.cluster.local:1337 |
| Grafana | http://grafana.observability.svc.cluster.local:3000 |
| Prometheus | http://prometheus.observability.svc.cluster.local:9090 |
| Miniflux | http://miniflux.services-it.svc.cluster.local:8080 |
| Immich | http://immich.media.svc.cluster.local:2283 |
| Karakeep | http://karakeep.services-it.svc.cluster.local:3000 |
| Music Assistant | http://music-assistant.home.svc.cluster.local:8095 |
| Gatus | http://gatus.ops.svc.cluster.local:8080 |
| Docmost | http://docmost.services-it.svc.cluster.local:3000 |
| Homebox | http://homebox.services.svc.cluster.local:3000 |
| LubeLog | http://lubelog.services.svc.cluster.local:3000 |
| Mind | http://mind.services-it.svc.cluster.local:8080 |
| SRM (Synology) | https://192.168.1.1:8001 |

## Discord

- Channel ID configuré : `1477772827091533976`
