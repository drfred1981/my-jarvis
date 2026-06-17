# Jarvis — Redéfinition de l'agent (définition + plan de code)

> Document de design. **Partie 1** = la nouvelle doctrine opératoire (destinée à
> remplacer/augmenter des sections de `CLAUDE.md` une fois validée). **Partie 2** =
> le plan d'implémentation, phasé. Le `CLAUDE.md` de production n'est PAS modifié
> tant que la Partie 1 n'est pas validée.

Décisions actées (session de cadrage) :
- **Périmètre** : définition + plan de code.
- **Backoff** : déterministe, en code Python (pas délégué au prompt).
- **Cadence** : deux pistes — monitoring infra (plancher) vs introspection idle (adaptatif).
- **Self-MR** : outils git-write MCP dédiés.
- **Git multi-repo** : `GITHUB_TOKEN` existant (avec **push**) + `GIT_REPOS` (plusieurs
  repos : infra, apps, jarvis…). Le git-write gère **tous** les repos de `GIT_REPOS`,
  pas seulement `my-jarvis` ; l'auto-modification du code Jarvis n'est qu'un cas
  particulier.
- **Modularité** : le code de l'agent est découpé en **plusieurs modules à périmètre
  clair**, jamais un seul gros script.

---

## Partie 1 — Doctrine opératoire de l'agent

### 1.1 Identité de conversation (keying)

Une conversation = une clé stable, qui remplace le `session_id` ad-hoc actuel :

| Source | Clé |
|---|---|
| Discord DM | `discord:dm:<user_id>` |
| Discord salon | `discord:channel:<channel_id>` |
| Discord thread | `discord:thread:<thread_id>` |
| Web UI | `web:<browser_session>` |
| Synology Chat | `synology:<user_id>` |
| Introspection autonome | `introspection` |
| Check infra | `monitor:<check>` |

Aujourd'hui le bot Discord keye sur `discord-{author.id}` seul : DM et salons d'un
même user se mélangent. Le nouveau keying les sépare et porte le mode (direct/multi).

### 1.2 Trois couches de contexte

1. **Transcript natif** — les fichiers `.claude/projects/<cwd>/<session_id>.jsonl`
   écrits par Claude Code lui-même. Historique verbatim tour-par-tour, repris via
   `--resume`. Survit au restart (volume persistant). C'est la « mémoire brute ».
2. **Contexte local** — `conversations/<clé>.md` dans le MCP `memory`. Digest
   *distillé* et structuré de cette conversation (participants, sujets en cours,
   décisions, préférences propres au canal). Distinct du transcript : c'est l'état
   utile, pas le verbatim. L'agent le met à jour ; il est chargé au début de chaque tour.
3. **Contexte global** — `global/state.md` dans `memory`. Vue synthétique de **tout
   le périmètre** : agrégat des conversations + infra + projets (Planka, repos,
   cluster). Maintenu par le cycle d'introspection profond. Injecté dans chaque
   conversation → les échanges locaux bénéficient du savoir global ; réciproquement,
   les faits locaux notables « remontent » dans le global lors de l'introspection.

**Index durable** : `conversations/index.json` (sur le volume) mappe
`clé → {claude_session_id, last_activity, mode, participants}`. Remplace le `dict`
en mémoire de `ClaudeRunner` → `--resume` et le suivi d'activité survivent au restart.

**Injection** : le dispatcher lit `conversations/<clé>.md` + `global/state.md`
directement sur le NFS et les **préfixe** au message (bloc contexte), plutôt que de
laisser l'agent faire des tool calls `memory` à chaque tour (gain tokens + latence).
L'agent peut toujours approfondir via le MCP `memory` si besoin.

### 1.3 Proactivité : backoff exponentiel déterministe, deux pistes

**Piste A — Monitoring infra (plancher de cadence).** Checks cluster/Flux/HA/Gatus :
cadence minimale garantie (~15 min), pause-sur-alerte-jusqu'à-acquittement (comme
aujourd'hui). Ce sont des besoins de type SLA — ils ne ralentissent pas la nuit.

**Piste B — Introspection/coaching (timer idle adaptatif).** Un timer unique
(conforme à unnamed4) :

- État : `last_user_activity` (mis à jour sur **tout** message user, tous canaux
  confondus) et `idle_interval` (départ 10 min). Persisté dans `introspection/state`.
- Boucle : dort `idle_interval` ; au réveil calcule `idle = now − last_user_activity`.
  - Un message user est arrivé pendant le sommeil → reset `idle_interval = 10 min`,
    on **skippe** l'introspection (les humains sont actifs : on reste réactif, on ne
    brûle pas de tokens à introspecter).
  - Sinon, profondeur selon `idle` :
    - `≤ 20 min` → **light** : check de présence, blocage évident ?
    - `≤ 80 min` → **medium** : scan de l'activité récente + un ou deux domaines,
      comparaison mémoire.
    - `> 80 min` → **deep** : revue de domaine complète (projets/Planka, infra,
      repos), comparaison avec `global/state.md`, mise à jour des fichiers de savoir,
      + **auto-introspection** (cf. 1.4).
  - Le prompt juge « worth saying ? » → **coaching personnalisé par utilisateur**
    (post ciblé : DM ou mention de l'utilisateur concerné, pas un canal unique
    générique) ou silence. Le canal coaching dédié reste une cible possible pour le
    coaching d'équipe ; l'individuel passe par la conversation de chaque user.
  - Double `idle_interval` (plafond 5 h).
- Sur **tout** message user (événement) : reset `idle_interval = 10 min`,
  `last_user_activity = now`.

**Gain clé** : Claude n'est invoqué qu'**au réveil**, et pas du tout si les users
sont actifs. Une nuit calme coûte une poignée d'appels (10, 20, 40, 80, 160, 300,
300… min) au lieu d'un appel toutes les quelques minutes court-circuité par le prompt.
→ Ceci **remplace** la section « Backoff adaptatif » actuelle du CLAUDE.md (le code
possède la cadence ; le prompt possède le jugement de contenu).

### 1.4 Introspection & auto-amélioration (multi-repo)

L'agent **gère plusieurs repos** (tous ceux de `GIT_REPOS` : infra, apps, jarvis…)
et peut proposer des changements sur **chacun** via MR. L'auto-modification du code
Jarvis (`my-jarvis`) n'est qu'un cas particulier de ce même mécanisme.

Le cycle **deep** inclut une étape d'auto-revue :

- Relire conversations/feedbacks récents → friction récurrente ? Proposer un nouveau
  **skill** (`skills/<nom>/SKILL.md`, hot-reload immédiat) ou un changement de code.
- Vérifier les autres contextes : « ai-je un outil/skill pour ça ? sinon, puis-je
  obtenir la donnée autrement ? » Croiser les contextes mémoire pour s'enrichir.
- Pour un changement de **code** (sur n'importe quel repo géré) : ouvrir une MR via le
  **MCP git-write** → `create_branch(repo, claude/<slug>)`, éditer (Write/Edit sur le
  clone `git-cache/<repo>`), `commit`, `push`, `open_pr` (gabarit
  Context / Changes / Tests / Risks), assigner un humain.
- Auth : `GITHUB_TOKEN` **déjà provisionné** et déjà utilisé en push (URLs
  authentifiées `https://{token}@github.com/…`, cf. `git/server.py:86`). Le git-write
  réutilise ce même token.
- **Garde-fou** : `main` protégée côté GitHub (par repo) → l'agent a le rôle
  *Developer* (propose) pas *Maintainer* (ne merge pas). Toute évolution est validée
  par un humain.

⚠️ **Hot-reload partiel** : skills et mémoire sont relus à chaque invocation (instant).
Le **code Python du service nécessite un redéploiement** → l'auto-amélioration code
passe par MR → merge humain → redeploy. À documenter pour ne pas survendre.

### 1.5 Modes de conversation

- **Direct** (DM ou salon à 2) : tous les messages traités.
- **Multi-user** (≥ 3 participants) : ne répondre qu'aux messages adressés à l'agent
  (`/claude <msg>` ou @mention), **mais lire tout le contexte** du salon. Le routeur
  décide « dois-je répondre ? » avant de spawn Claude ; dans tous les cas il peut
  alimenter le contexte local du salon.

---

## Partie 2 — Plan d'implémentation (phasé)

### Principe transverse — code modulaire

Chaque ajout est découpé en **modules à périmètre clair**, jamais un gros script.
Découpage cible (chaque fichier ≈ une responsabilité) :

```
src/dispatcher/
  conversations/
    registry.py      # CRUD + persistance de l'index (clé → session)
    keys.py          # construction/parse des clés (discord:dm:…, etc.)
  context/
    injector.py      # lecture NFS local+global, assemblage du bloc contexte
  proactive/
    monitor.py       # Piste A — checks infra (plancher de cadence)
    introspector.py  # Piste B — timer idle adaptatif + profondeurs
    prompts.py       # templates light/medium/deep + check infra
src/mcp-servers/git-write/
  server.py          # surface MCP (@mcp.tool) + câblage — fin, délègue
  repos.py           # résolution GIT_REPOS, URL authentifiée, cache clone
  branches.py        # create/checkout + garde-fou (refuse main, n'autorise claude/*)
  commits.py         # add/commit/push
  pulls.py           # API GitHub PR (httpx) : open_pr, pr_status
```

Un `server.py` MCP reste l'unique *entrypoint* (pointé par `mcp.json`) mais
**importe** des modules frères : il ne contient que le câblage des outils, la logique
vit dans les modules dédiés.

### Phase 0 — Registry de conversations (fondation) ✅ FAIT

**Package `src/dispatcher/conversations/`** (modulaire) :
- `keys.py` : builders/parse des clés structurées (`discord:dm:…`, `monitor:…`,
  `introspection`) + `is_user()` (distingue conversations humaines des pistes système).
- `registry.py` : `Conversation` dataclass + `ConversationRegistry` (store
  thread-safe, JSON atomique). API : `get_or_create`, `touch`, `record_session_id`,
  `reset_session`, `clear`, `list`, `count`, `last_user_activity()` (max sur les
  conversations *user* uniquement → alimentera le timer Piste B). Module pur, sans
  couplage métriques/framework.
- Persistance : `$JARVIS_PROJECT_DIR/.claude/conversations-index.json`, chargé au
  startup, écrit atomiquement (tmp + `os.replace`). Survit au restart.

**`claude_runner.py`** : `dict` interne remplacé par le `ConversationRegistry` ;
`send_message(conversation_key, …)` persiste le `claude_session_id` capturé dans le
registry ; `touch()` à chaque message ; `ACTIVE_SESSIONS` piloté par `count()`.

Vérifié : AST OK + smoke-test (keys, round-trip persistance, `last_user_activity`,
reload disque, clear). Aucun comportement visible changé.

### Phase 1 — Injection contexte local + global ✅ FAIT

**Package `src/dispatcher/context/`** (modulaire) :
- `injector.py` : lit `<memory_dir>/global/state.md` (toujours) et
  `<memory_dir>/conversations/<clé>.md` (conversations *user* seulement) sur le NFS
  (`JARVIS_MEMORY_DIR`), assemble un bloc borné (caps 4000 car/section, troncature
  signalée) et le préfixe au message. `local_context_name(key)` mappe la clé en nom
  slug-safe (`discord:dm:1` → `conversations/discord-dm-1`) pour que lecture (Phase 1)
  et écriture (Phase 3) s'accordent. Garde anti-traversal sur les chemins.

**`claude_runner.py`** : `send_message(…, with_context=True)` préfixe le bloc via
`injector.inject()` avant le spawn (`-p prompt`).

**Non-disruptif** : fichiers absents → bloc vide → no-op total. L'injection ne fait
effet qu'une fois les contextes écrits (introspection Phase 2 / doctrine Phase 3).

**Doctrine prompt (reportée en Phase 3)** : instruire l'agent à entretenir
`conversations/<clé>` (sous le nom exact de `local_context_name`) et à faire remonter
le notable dans `global/state`.

*Décision actée : injection inline depuis le NFS (déterministe, sans tool call)
plutôt que de laisser l'agent charger via le MCP `memory` à chaque tour.*

Vérifié : AST + smoke-test (mapping de nom, no-op si absent, global-only pour
monitor/user-sans-local, troncature, garde traversal) + `task validate` global.

### Phase 2 — Scheduler en deux pistes ✅ FAIT

Paramètres de cadence actés : **plancher 15 min ferme** (Piste A, pas de backoff) ;
**backoff exponentiel 15→30→60→120→240→300 (cap 5 h)** sur la Piste B tant qu'il n'y
a pas d'activité chat récente, reset à 15 min sur message ; **mode nuit 00h–07h** qui
suspend les **deux** pistes (réactif toujours actif) ; **réveil** sur message chat ;
**coaching individuel en plus de l'équipe**.

**Package `src/dispatcher/proactive/`** (modulaire) :
- `quiet.py` : mode nuit (`JARVIS_QUIET_HOURS`, fenêtres wrap-around), helpers purs.
- `prompts.py` : templates introspection light/medium/deep + coaching individuel
  (le contenu et le jugement « worth saying ? » vivent ici, pas la cadence).
- `monitor.py` (relocalisé depuis `dispatcher/monitor.py`, Piste A) : + plancher
  `JARVIS_MONITOR_FLOOR_MIN=15`, + garde mode nuit, + clés `monitor:<check>`.
- `introspector.py` (Piste B) : timer idle adaptatif (event de réveil + backoff ×2),
  profondeur selon idle, suppression nuit, **skip si chat actif** (reste réactif sans
  brûler de tokens). Coaching **équipe** (`notify_coaching`) chaque cycle utile ;
  **individuel** (cycles deep) → pour chaque user DM-able actif < 24 h, prompt dans le
  contexte de SA conversation puis `notify_user` (DM Discord).

**`notifier.py`** : `notify_coaching` (canal dédié `DISCORD_COACHING_CHANNEL_ID` sinon
broadcast) + `notify_user` (DM Discord). **`discord_bot.py`** : `send_dm` + clés
structurées (dm/thread/channel) + `is_user_initiated=True`. **`claude_runner.py`** :
hook `add_activity_listener` ; `touch`/réveil **seulement** sur messages user réels
(les envois auto de coaching ne comptent pas comme activité). **`main.py`** : câblage
Introspector + clés `web:`/`synology:` + listener d'activité.

Vérifié : `task validate` + tests unitaires (quiet hours wrap-around, depth, backoff
exact, `is_clear`, dm_target) + test d'intégration async du cycle (coaching équipe +
individuel ciblé, clear session, pas de fausse activité).

*Backoff retiré du prompt : le code possède la cadence, le prompt le contenu.*

### Phase 3 — MCP git-write (multi-repo) + auto-amélioration + doctrine ✅ FAIT

Livré : package `src/mcp-servers/git-write/` (`server.py` fin + `repos.py` +
`branches.py` + `commits.py` + `pulls.py` + `requirements.txt` + `README.md`).
Outils : `list_writable_repos`, `create_branch`, `commit_changes`, `push`, `open_pr`,
`pr_status`. Guardrails : seules les branches `claude/*`, jamais de push/commit sur une
branche protégée, jamais de merge. Câblé dans `mcp.json` + `services.py`
(`git-write` → `GITHUB_TOKEN` + `GIT_REPOS`) ; `--allowedTools` ajoute
`mcp__git-write__*` automatiquement. Doctrine `CLAUDE.md` réécrite : section backoff
remplacée par « la cadence est dans le code », + sections Contextes local/global et
Introspection & auto-amélioration (workflow MR), + capacité git-write.

Vérifié : `task validate` ; tests des helpers/guardrails (slug, prefix, protected) ;
**test bout-en-bout réel** (clone → create_branch → edit → commit → push) contre un
dépôt bare local → branche `claude/*` poussée, guardrail commit-sur-main bloqué.

Plan initial (pour mémoire) :

**Nouveau package `src/mcp-servers/git-write/`** (modulaire, cf. principe transverse) :
- `server.py` — surface MCP fine : `create_branch(repo, name, base="main")`,
  `commit(repo, message, files)`, `push(repo, branch)`,
  `open_pr(repo, title, body, base, head)`, `pr_status(repo, number)`. Délègue à :
- `repos.py` — résout **n'importe quel** repo de `GIT_REPOS` (pas seulement jarvis),
  construit l'URL authentifiée avec `GITHUB_TOKEN`, localise le clone
  `$JARVIS_PROJECT_DIR/git-cache/<repo>`.
- `branches.py` — branche/checkout + **garde-fou** : refuse tout push sur `main`,
  n'autorise que `claude/*`.
- `commits.py` — add/commit/push.
- `pulls.py` — API GitHub PR via `httpx` (`open_pr` cible `main` mais ne merge
  jamais ; `pr_status`).
- Éditions de fichiers : via Write/Edit built-in sur `git-cache/<repo>/…`, puis
  commit/push/PR via le MCP.
- Auth : **réutilise `GITHUB_TOKEN`** (déjà provisionné et déjà utilisé en push par le
  git MCP read-only) — pas de nouveau secret à créer.
- **Câblage (3 endroits)** : `mcp.json` + `services.py` `SERVICE_REQUIREMENTS`
  (`git-write` → `GITHUB_TOKEN` + `GIT_REPOS`) + `get_allowed_tools_string`.

**Prérequis externes** : branch protection réelle sur `main` **par repo géré** côté
GitHub (sinon le garde-fou Developer/Maintainer n'est pas effectif) ; vérifier que le
token a bien le scope PR (`pull_requests:write`) en plus du push déjà fonctionnel.

**Réécriture `CLAUDE.md`** (application de la Partie 1) :
- Remplacer « Backoff adaptatif » → « Cadence : le code gère le timing (deux pistes),
  tu juges le contenu et le “worth saying ?” ».
- Ajouter « Contextes local/global » (usage `conversations/<clé>` + `global/state`).
- Ajouter « Introspection & auto-amélioration » (cycle deep + workflow MR git-write).
- Ajouter « Modes de conversation » (direct vs multi-user `/claude`).
- Conserver persona, anti-doublons Planka, git-sync, scripts fredtool/jarvis.

### Phase 4 — Modes Discord + heartbeats (finition) ✅ FAIT

**`channels/discord_bot.py`** : `_resolve_conversation` → (mode, clé) : DM=direct ;
salon dans `DISCORD_CHANNEL_IDS`=direct (always-on) ; group DM ≤2=direct ; salon
guild/thread=multiuser. En multiuser, `parse_invocation` (pur, testé) n'agit que sur
`/claude …` ou @mention ; sinon lecture seule. Quand invoqué, `_recent_history` (≤15
msgs) préfixe le contexte du salon avant « Message adressé à toi ». Le mode est persisté
(`registry.set_mode`).

**Heartbeats** : `claude_runner.send_message(…, heartbeat=cb, heartbeat_interval=30)` +
`_heartbeat_loop` (task asyncio, annulée en `finally`). Discord fournit un callback qui
envoie/édite un message « ⏳ Je travaille toujours… (Ns) » puis le supprime à la fin —
un seul message, pas de spam ; rien si la réponse arrive en < 30 s.

Vérifié : `task validate` + tests purs (`parse_invocation` mention/`/claude`/ignore,
`set_mode` + persistance, `_heartbeat_loop` tick+cancel). Doctrine `CLAUDE.md` :
section « Modes de conversation » ajoutée.

**Refonte complète : les 5 phases (P0→P4) sont livrées et testées.**

### Extension — Auto-amélioration des compétences (skills scopés) ✅ FAIT

Les skills deviennent des compétences acquérables et scopables :
- **MCP `skills`** (`src/mcp-servers/skills/` : `server.py` fin + `catalog.py` +
  `attachments.py`) : `list_skills`, `read_skill`, `create_skill` (acquérir une
  compétence manquante, hot-reload immédiat), `attach_skill`/`detach_skill`/
  `list_conversation_skills` (compétences propres à une conversation).
- **Injection** (`context/skills.py` + `injector.py`) : catalogue global (nom+desc)
  injecté dans chaque conversation user/introspection → l'agent connaît tout son
  répertoire ; skills **attachés** injectés en entier dans LEUR conversation →
  compétences propres. L'en-tête du bloc rappelle la clé de conversation (pour
  `attach_skill` / `save_context`).
- **Stockage partagé** : attachements sur le NFS
  (`<memory>/skill-attachments/<clé>.json`) → le MCP écrit, l'injecteur (autre process)
  lit la même source. Contrat vérifié par test bout-en-bout.
- **Câblage** : `mcp.json` + `services.py` (`skills` → `type: always`, comme `memory`).
- **Doctrine `CLAUDE.md`** : section « Compétences (skills) » (globales / par conversation /
  auto-amélioration : `list_skills` → `attach_skill` → sinon `create_skill`), + lien
  depuis le cycle d'introspection deep.

Vérifié : `task validate` + test bout-en-bout (create_skill → attach → l'injecteur
surface le catalogue global + le skill attaché ; detach → disparaît ; gating
user/introspection vs monitor).

---

### Extension — Repos gérés : une conversation dédiée par repo ✅ FAIT

Mécanique : `GIT_REPOS` (JSON) → pré-clone + `pull --rebase` au `docker run`
(`_preclone_git_repos`, existant) ; chaque repo a sa conversation/thread dédiée que
**l'agent pilote** ; sync avant action assurée par le `fetch`/`reset` de `create_branch` ;
documentation systématique à chaque évolution.

Décisions actées : mapping repo↔salon = **threads créés par l'agent** (piloté, pas de
config statique) ; sync = **s'appuyer sur l'existant + doctrine** ; documentation = **les
4** (docs in-repo + CHANGELOG + carte Planka + corps de MR structuré).

Implémentation (léger, doctrine-first) :
- **Skill `skills/repo-workflow/SKILL.md`** : encode la procédure (binding repo↔conv →
  sync → changement → docs in-repo + CHANGELOG + Planka → MR Context/Changes/Tests/Risks
  → clôture). À `attach_skill` sur chaque conversation de repo (dogfooding du système de
  skills). Vérifié : parsé par le catalogue.
- **Doctrine `CLAUDE.md`** : section « Repos gérés : une conversation dédiée par repo ».
- **MCP `discord-write`** (`src/mcp-servers/discord-write/` : `server.py` fin + `api.py`) :
  `create_thread`, `post_message`, `list_active_threads` via l'API REST Discord (pas de
  gateway — adapté aux subprocess MCP), auth token du bot. → l'agent crée **réellement**
  le thread dédié par repo (step 0 du skill `repo-workflow`). Câblé `mcp.json` +
  `services.py` (`discord-write` → `DISCORD_BOT_TOKEN`). Salon parent optionnel via
  `DISCORD_REPO_PARENT_CHANNEL_ID`. Vérifié : tests REST (paths, type public/privé,
  header `Bot`, chunking, garde no-token).

### Déploiement (image vs volume persistant) ✅ FAIT

Contrainte : l'app vit dans l'image (`/opt/jarvis/app`, à jour à chaque redeploy) mais
le runtime tourne avec `cwd=/home/jarvis` (volume persistant), seedé par `entrypoint.sh`.

Problèmes trouvés + corrigés :
- **Skills non seedés** : Dockerfile ne copiait pas `skills/` dans le seed → ajouté
  (`COPY skills/ /opt/jarvis/seed/skills/`) + bloc entrypoint « new-only » (les skills
  créés/édités au runtime persistent).
- **Config jamais mise à jour** : `CLAUDE.md` + `mcp.json` étaient seedés « only-if-absent »
  → un redeploy sur volume existant n'appliquait NI mes nouveaux MCP (git-write, skills,
  discord-write) NI la doctrine réécrite. **Fix** : `docker/seed_merge.py` (stdlib) +
  entrypoint **mergent** le seed dans le runtime à chaque boot :
  - `mcp.json` : union des `mcpServers` (seed gagne par clé, serveurs volume-only conservés) ;
  - `CLAUDE.md` : merge par sections `## ` (seed gagne sur ses sections, sections
    volume-only conservées). Idempotent, testé (union, fresh, préservation, self-merge).
  `memory/`, `.claude/`, `skills/` restent persist-only (état runtime).

À vérifier côté prod (pré-existant, pas modifié) : l'entrypoint seede `memory/*.md` vers
`/home/jarvis/.claude/projects/-home-jarvis/memory` (auto-mémoire Claude Code) alors que
le MCP `memory` lit `/home/jarvis/memory` (`JARVIS_MEMORY_DIR`) — deux stores distincts.
Mes features sont cohérentes (injecteur + MCP memory + attachements partagent
`JARVIS_MEMORY_DIR`), mais le savoir « shipped » n'est pas exposé via `load_context`.

## Décisions techniques résiduelles à confirmer

1. **Emplacement de l'index conversations** : `.claude/conversations-index.json`
   (proche des transcripts) vs contexte `memory` (`conversations/index`). → reco :
   `.claude/` (cohérent avec les sessions natives).
2. **Canal coaching** : un salon Discord dédié (`DISCORD_COACHING_CHANNEL_ID`) ?
3. **Plancher Piste A** : 15 min ferme, ou mode nuit (ex. ×2 entre 22 h–7 h) ?
4. **Heartbeats** : in-scope maintenant ou Phase 4 « nice-to-have » ?
5. **Token GitHub** : le push fonctionne déjà (`GITHUB_TOKEN`). Reste à confirmer le
   scope `pull_requests:write` + branch protection active **sur chaque repo géré**.
