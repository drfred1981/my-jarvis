---
name: repo-workflow
description: Procédure pour travailler un repo géré (GIT_REPOS) dans sa conversation dédiée — création du thread, sync, MR, documentation systématique. À attacher à chaque conversation/thread de repo.
tools: git, git-write, discord-write, planka, memory, skills
---

# repo-workflow — travailler un repo géré

Chaque repo de `GIT_REPOS` a **sa conversation dédiée** (un thread Discord dédié). Quand
tu travailles un repo dans sa conversation, suis cette procédure de bout en bout.

## 0. Thread dédié + binding (une fois par repo)

- **Retrouve ou crée le thread** du repo via le MCP `discord-write` :
  `list_active_threads(<guild_id>)` → si aucun thread nommé `<repo>`,
  `create_thread(<parent_channel_id>, "<repo>")`. Le `parent_channel_id` est le salon
  parent dédié aux repos (`DISCORD_REPO_PARENT_CHANNEL_ID` si défini, sinon demande-le).
  La réponse te donne la `conversation_key` `discord:thread:<id>`.
- **Enregistre le binding** dans le contexte local de cette conversation :
  `save_context("conversations/<clé>", "Conversation dédiée au repo <name> (<url>, branche <base>).")`
  (la `<clé>` est rappelée dans l'en-tête du bloc de contexte injecté).
- **Attache-toi cette compétence** si ce n'est pas déjà fait :
  `attach_skill("<clé>", "repo-workflow")`.
- Annonce dans le thread (`post_message`) que tu pilotes désormais ce repo ici.

## 1. Synchroniser AVANT toute action

- `create_branch(repo, "claude/<slug>")` resynchronise déjà (fetch + reset sur
  `origin/<base>`) — c'est ta porte d'entrée normale pour modifier un repo.
- Pour une simple lecture/analyse, le repo est rafraîchi au démarrage (pré-clone
  `pull --rebase`) et par le MCP `git`. En cas de doute, repars d'une branche fraîche.
- Ne travaille jamais sur une branche protégée ; uniquement `claude/*`.

## 2. Faire le changement

Édite les fichiers sous le `path` renvoyé par `create_branch` (Write/Edit).

## 3. Documentation systématique (obligatoire à CHAQUE évolution)

1. **Docs in-repo** : mets à jour le `README.md` et/ou `docs/` du repo dans la **même
   branche** que le changement.
2. **CHANGELOG** : ajoute une entrée (date + résumé) au `CHANGELOG.md` (crée-le s'il
   n'existe pas).
3. **Carte Planka** : crée/mets à jour une carte de suivi sur le board du projet —
   **vérifie l'anti-doublon d'abord** (cf. règle Planka), commente si la carte existe.

## 4. Proposer la MR

`commit_changes(repo, msg)` → `push(repo)` → `open_pr(repo, title, body, …)`.
Le **corps de MR** doit couvrir :

```
## Context   — pourquoi ce changement
## Changes   — ce qui change (fichiers, comportement)
## Tests     — comment c'est vérifié
## Risks     — risques / points d'attention pour le reviewer
```

Garde-fou : tu **proposes** (rôle Developer), un humain review et merge. Tu ne merges
jamais.

## 5. Clôturer

- Mets à jour `global/state` (note l'évolution proposée + lien MR) et le contexte local.
- Poste la synthèse (lien MR) dans la conversation dédiée du repo.
