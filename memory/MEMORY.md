# Jarvis Memory

## Planka - Suivi des tâches

### Consigne : Monitoring → Cartes Planka
Quand je fais une surveillance/check de monitoring, je dois **créer des cartes Planka** dans le projet **Home-Automation** pour tracer les anomalies détectées et les actions à mener. Toutes les remarques doivent être **traduites en français**.

### Consigne : Workflow cartes Planka (tous projets)
- Quand une carte passe de **"A faire" / "À faire" → "En cours"**, cela signifie que l'utilisateur veut que je **traite cette tâche immédiatement**
- Une fois la tâche terminée, je dois **déplacer la carte vers "Fait"**
- Je dois surveiller les cartes "En cours" et agir dessus proactivement
- S'applique aux projets **MCO**, **Apps** et **Home-Assistant**

### Consigne : Projet Apps - Améliorations fonctionnelles
- Les idées d'améliorations, nouvelles apps, fonctionnalités vont dans le projet **Apps**
- Liste "Idées / Backlog" : idées à évaluer
- Liste "À faire" : validé, à réaliser quand passé en "En cours"
- Quand je détecte des améliorations fonctionnelles possibles, les consigner en carte dans ce projet

### Consigne : Projet Home-Assistant - Automations & Fonctionnalités
- Les idées d'améliorations HA (automations, scènes, notifications, nettoyage) vont dans le projet **Home-Assistant**
- Même workflow que les autres projets (Backlog → À faire → En cours → Fait)
- Quand je détecte des améliorations possibles côté domotique, les consigner en carte dans ce projet

### Consigne : Détail des cartes Planka
- **Création** : description complète (contexte, symptômes observés, impact, pistes de résolution)
- **En cours** : ajouter des commentaires à chaque étape (diagnostic, actions, commits, résultats intermédiaires)
- **Fermeture** : commentaire de synthèse (actions réalisées, commits associés, vérification du résultat) puis déplacement vers "Fait"

### Projet MCO - Maintenance K8s (actif)
- Project ID: `1723377741660685346`
- Board "Taches" ID: `1723377742340162596`
- Liste "A faire" ID: `1723377837383091242`
- Liste "En cours" ID: `1723377838054179883`
- Liste "Fait" ID: `1723377838549107756`

### Projet Apps - Fonctionnalités & Déploiements (actif)
- Project ID: `1723395074294809677`
- Board "Suivi" ID: `1723395177986393168`
- Liste "Idées / Backlog" ID: `1723395178263217236`
- Liste "À faire" ID: `1723395178397434965`
- Liste "En cours" ID: `1723395178540041302`
- Liste "Fait" ID: `1723395178682647639`

### Projet Home-Assistant - Automations & Fonctionnalités (actif)
- Project ID: `1723399318234203227`
- Board "Suivi" ID: `1723399318427141213`
- Liste "Idées / Backlog" ID: `1723399318645245025`
- Liste "À faire" ID: `1723399318771074146`
- Liste "En cours" ID: `1723399318922069091`
- Liste "Fait" ID: `1723399319156950116`

### Note technique MCP Planka
- Le tool MCP `list_projects` retourne une liste vide (bug sérialisation grands IDs)
- Contournement : utiliser l'API REST directe via `requests` Python avec credentials en variables d'env (`PLANKA_URL`, `PLANKA_USER`, `PLANKA_PASSWORD`)

### Note technique API Planka
- Le champ `type` est obligatoire pour créer un projet (`private`, `shared`), une liste (`active`, `closed`), une carte (`project`, `story`)
- **Endpoint création de carte** : `POST /api/lists/{list_id}/cards` (PAS `/api/boards/{board_id}/lists/{list_id}/cards`)
- **Endpoint commentaire** : `POST /api/cards/{card_id}/comments` (body: `{"text": "..."}`)
- **Endpoint déplacement carte** : `PATCH /api/cards/{card_id}` (body: `{"listId": "...", "position": 65536}`) — `position` est obligatoire
- **Endpoint lecture board** : `GET /api/boards/{board_id}` — les cartes sont dans `included.cards`
- Le `defaultCardType` du board Taches est `project`
- Les outils MCP Planka `get_board` échouent (IDs parsés en int). Contournement : API REST directe

### Note technique MCP FluxCD
Les outils MCP FluxCD retournent **Forbidden**. Contournement : utiliser la CLI `flux` directement via Bash.

## Règle GitOps : pérenniser les changements K8s
**Toute ressource Kubernetes créée/modifiée doit être commitée dans le repo `apps-in-k8s`** (`/home/jarvis/git-cache/apps-in-k8s/`), jamais uniquement via `kubectl apply`.
- Structure : `kubernetes/apps/<namespace>/<app>/app/`
- Ajouter les nouveaux fichiers dans le `kustomization.yaml` de l'app
- Le namespace est défini au niveau parent (`kubernetes/apps/<ns>/kustomization.yaml`), ne pas le mettre dans les manifests
- Conventions commits : `feat(<app>): ...`, `fix(<app>): ...`
- Les configs HA (automations.yaml, configuration.yaml) vivent dans le PVC, c'est normal

## Home Assistant - Best Practices intégrées
Référence complète dans [ha-best-practices.md](ha-best-practices.md) (source: homeassistant-ai/skills).
Principes clés à appliquer systématiquement :
- **Conditions/triggers natifs** avant tout template (numeric_state, time, sun, state)
- **Helpers intégrés** avant template sensors (min_max, threshold, derivative, utility_meter, group, schedule)
- **Bon mode d'automation** : restart (motion lights), queued (séquentiel), parallel (multi-entité)
- **entity_id** au lieu de device_id (sauf Z2M autodiscovered)
- **ZHA boutons** : event trigger + device_ieee (persistant)
- **Safe refactoring** : chercher TOUS les consommateurs avant de modifier
- **Templates OK** pour : données dynamiques service calls, notifications, trigger context, itération entités

## Liens vers fichiers détaillés
- [planka-cards.md](planka-cards.md) - Détails des cartes existantes
- [ha-best-practices.md](ha-best-practices.md) - Best practices Home Assistant complètes
