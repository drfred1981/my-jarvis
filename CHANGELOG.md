# Changelog

Toutes les évolutions notables de Jarvis. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [Non publié]

### Added
- **Sensibilisation aux capacités BMAD dans le contexte injecté.** Jarvis connaît
  désormais, dans chaque conversation utilisateur/introspection, le catalogue des
  workflows BMAD installés sous `_bmad/` (BMad Method + modules `wds`/`cis`/`tea`/`bmb`
  + `bmad-loop`) : nom + code menu, groupés par module. Nouveau `src/dispatcher/context/bmad.py`
  (lecture des `_bmad/*/module-help.csv`, bloc compact borné à 2600 car.), câblé dans
  `context/injector.py` sous la même garde que le catalogue de skills (pistes
  monitoring/système exclues). Le Dockerfile embarque les `module-help.csv` dans le seed
  (`.dockerignore`/`.gitignore` ne laissent passer que les catalogues, pas la config
  perso ni les corps de skills). Objectif : que les demandes Discord portant sur la
  conduite d'un projet logiciel (cadrage, PRD, architecture, sprint, review) soient
  traitées avec la grille BMAD plutôt qu'en improvisant.

### Fixed
- **Pod bloqué au démarrage par le nettoyage des locks git (virtiofs/NFS).** L'entrypoint
  faisait un `find … -delete` récursif sur **tout** `git-cache` (arbres de travail entiers) ;
  sur virtiofs le `find` peut staller en attente FUSE (`request_wait_answer`) et bloquer
  indéfiniment l'entrypoint → le dispatcher ne démarrait jamais. Désormais le balayage est
  scopé aux seuls dossiers `.git` et **borné par un `timeout` par dépôt** (best-effort).
- **Pod bloqué au démarrage par l'auth OAuth des MCP distants claude.ai.** `claude` était
  lancé avec `--mcp-config` mais **sans `--strict-mcp-config`** → il chargeait aussi les
  connecteurs de compte claude.ai (Gmail/Calendar/Drive), dont l'init OAuth **interactif**
  bloque indéfiniment en pod headless → le CLI ne rendait jamais la main, le dispatcher ne
  démarrait pas (uvicorn HTTP 000). Ajout de `--strict-mcp-config` : `claude` n'utilise que
  l'ensemble MCP filtré par jarvis (`mcp.json` + `services.py`), rien d'autre.
- **Crash au démarrage `NameError: name 'asyncio' is not defined`.** `main.py` utilisait
  `asyncio` (`_memory_gauge_loop`, `asyncio.sleep`) sans l'importer → le lifespan `startup`
  levait une exception. Ajout de `import asyncio`.
- **Continuité de conversation perdue (contexte oublié).** Le runtime passait
  `--session-id` à *chaque* appel `claude -p` et **jamais `--resume`** : sur la version
  `claude` déployée, réutiliser un `--session-id` ne reprenait pas la session → contexte
  oublié à chaque tour. Désormais une conversation utilisateur **établit** sa session au
  1ᵉʳ tour (Claude génère l'id, qu'on **capture**), puis la **reprend via `--resume <id>`**
  à chaque tour suivant. Un transcript perdu (recréation de pod) **s'auto-répare** en
  ré-établissant une session neuve. État `session_started` + id réel persistés dans le
  `ConversationRecord`. Les pistes système (`monitor:*`, `introspection`) restent
  éphémères.

### Added
- **Skill `coach` + redéfinition du coaching.** `coaching` n'est plus une notification
  proactive mais l'**accompagnement** (posture par défaut des conversations utilisateur) :
  procédure complète dans `skills/coach/SKILL.md` (versionné, hot-reload) et essentiel dans
  `CLAUDE.md` (deux casquettes accompagner/proposer, seuil valeur≫coût, échelle d'intervention,
  apprentissage des refus, garde-fous). Le coach tient objectifs/état/écart/refus dans la
  mémoire locale `conversations/<clé>`.
- **Mapping conversation → données techniques (`ConversationRecord`).** Le registry
  devient la source de vérité unique indexée par l'ID global de la conversation (slug
  couplé au transport). Chaque record résout toutes les poignées techniques :
  - **`session_id` déterministe** : `uuid5(namespace, clé)` — reproductible sans état
    stocké (et stocké quand même pour rester observable). Les conversations utilisateur
    reprennent via `claude --session-id` (idempotent : reprend si le transcript existe,
    sinon le crée) → **fin des échecs `--resume` sur session perdue** ; les pistes
    système (`monitor:*`, `introspection`) restent éphémères (session neuve par cycle).
  - **`description`** : contexte minimal seedé depuis `DISCORD_CHANNEL_IDS`.
  - résolveurs canoniques `keys.session_id/context_name/slug` (partagés injecteur/skills).
- **`DISCORD_CHANNEL_IDS` structuré.** Accepte désormais une liste JSON
  `[{"id","description"}]` (en plus du CSV legacy, auto-détecté). La `description` seed le
  **cadrage** de la conversation (injecté en tête), déclaratif et re-seedé à chaque boot ;
  la mémoire runtime n'est jamais écrasée. `id` requis, `description` optionnelle (inférée
  sinon).

### Fixed
- **Routage proactif cloisonné par conversation.** Le monitoring (Piste A) et la revue de
  périmètre ne sont plus diffusés à l'identique dans **tous** les canaux Discord
  (`notify_all`). Désormais :
  - le **monitoring** va à son **seul canal dédié** (`JARVIS_MONITOR_CHANNEL_ID`,
    fallback canal opérateur puis log-only — jamais de broadcast) ;
  - la **revue de périmètre** (introspection — digest opérateur, plus « coaching équipe »)
    ne va qu'au canal dédié (`DISCORD_COACHING_CHANNEL_ID`) ou est journalisée — plus de
    fallback broadcast ;
  - le **coaching par conversation** (posture coach, cycles deep) est généré avec le contexte
    local de chaque conversation active et posté **dans cette conversation** via le nouveau
    primitif `Notifier.notify_conversation()` (qui route vers l'unique destination encodée
    dans la clé : canal/thread/DM Discord, session web, Synology).
  Met en œuvre la doctrine d'isolation de sortie + la redéfinition du coaching (`CLAUDE.md`).

### Changed
- **Doctrine — adaptation au contexte de chaque conversation.** Ajout dans `CLAUDE.md`
  (system prompt runtime) d'une règle cardinale : la sortie est **cloisonnée par
  conversation** (jamais de monitoring infra dans une conversation dédiée ; coaching
  spécifique au contexte de la conversation), tandis que le savoir reste **mutualisé**
  via `global/state` (vue d'ensemble, corrélation inter-conversations). Pérenne par
  construction : re-seedée à chaque déploiement par `docker/seed_merge.py`.
- **Skills : repo figé + amendement runtime (deux couches, lecture en union).** Les skills
  du repo (image, `JARVIS_SKILLS_SEED_DIR=/opt/jarvis/seed/skills`) sont la **source de
  vérité figée** — lus en lecture seule, rafraîchis à chaque déploiement, **prioritaires sur
  collision de nom**. Les skills runtime (`create_skill`, volume `JARVIS_SKILLS_DIR`) sont un
  **amendement** qui s'ajoute par-dessus sans jamais masquer un skill du repo. Avant, le
  seeding copiait les skills sur le volume « new only » → un skill repo mis à jour ne se
  propageait jamais, une édition runtime le masquait (pas figé). Désormais :
  - `entrypoint.sh` **ne sème plus** les skills sur le volume (lecture en place depuis l'image) ;
  - `catalog.py` (MCP) et `context/skills.py` (injection) lisent l'**union** des deux dossiers,
    repo prioritaire ;
  - `create_skill` **refuse** un nom de skill du repo (→ proposer une MR), et écrit toujours
    côté runtime.

### Fixed
- **Warning `no stdin data received in 3s`** : le subprocess `claude` reçoit désormais
  `stdin=DEVNULL` (plus d'attente de 3 s ni de bruit dans les logs).
