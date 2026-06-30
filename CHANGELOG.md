# Changelog

Toutes les évolutions notables de Jarvis. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [Non publié]

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

### Changed
- **Doctrine — adaptation au contexte de chaque conversation.** Ajout dans `CLAUDE.md`
  (system prompt runtime) d'une règle cardinale : la sortie est **cloisonnée par
  conversation** (jamais de monitoring infra dans une conversation dédiée ; coaching
  spécifique au contexte de la conversation), tandis que le savoir reste **mutualisé**
  via `global/state` (vue d'ensemble, corrélation inter-conversations). Pérenne par
  construction : re-seedée à chaque déploiement par `docker/seed_merge.py`.

### Fixed
- **Warning `no stdin data received in 3s`** : le subprocess `claude` reçoit désormais
  `stdin=DEVNULL` (plus d'attente de 3 s ni de bruit dans les logs).
