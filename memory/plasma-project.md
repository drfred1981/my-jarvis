---
name: Plasma - Moteur de navigation 2D
description: Projet Java/Spring Boot - moteur 2D avec visibilité, pathfinding A*, fog of war, WebSocket temps réel. Repo git-cache/plasma.
type: project
---

## Plasma — Plateforme de visualisation de robots multiagents

**Repo** : `/home/jarvis/git-cache/plasma/` (GitHub: drfred1981/plasma)
**Stack** : Java 17, Spring Boot 3.2, WebSocket, vanilla JS + Canvas
**Port** : 8888
**Build** : `mvn compile`, `task docker-build`

### Architecture (8 packages)
- **geometry/** — Primitives (Vec2 record, Polygon, AABB, LineSegment, GeomMath)
- **world/** — World container, Obstacle (static/dynamic), ObstacleManager (grille spatiale), WorldFactory, MazeGenerator
- **collision/** — CollisionDetector (circle collision + wall sliding)
- **vision/** — VisionFinder (angular sweep FOV), FogOfWar (grille boolean)
- **path/** — PathFinder (A* sur graphe de visibilité), NavMesh, NodeConnector
- **character/** — GameCharacter (position, path, FOV, fog)
- **engine/** — GameLoop (60Hz fixe, broadcast 20 FPS)
- **web/** — WebSocket handler (/ws/game), DTOs, config

### Communication
WebSocket bidirectionnel JSON sur `/ws/game`. Serveur broadcast `WorldStateDto` toutes les 3 ticks (~20 FPS). Client envoie commandes : moveCharacter, addObstacle, removeObstacle, addCharacter, newWorld.

### Frontend
Single-page : index.html + main.js (IIFE) + style.css. Modes : Move, Draw, Delete, +Char. Toggles : FOV, Fog, Paths, Grid. Modal "New World" (field/maze config).

### Algorithmes clés
- Visibilité : angular sweep O(V×E)
- Pathfinding : A* sur visibility graph O(n²) construction
- Maze : recursive backtracking
- Collision : circle + wall sliding
- Spatial index : grid-based O(1)

### État actuel
- En cours de construction (pas de tests unitaires)
- Pas de persistence/save
- Obstacles dynamiques (pulsing, linear, rotating)

**Why:** Le user développe activement ce projet, il faut pouvoir y contribuer efficacement.
**How to apply:** Utiliser ce contexte pour comprendre les demandes liées à Plasma sans re-explorer le code.
