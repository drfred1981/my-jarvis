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
