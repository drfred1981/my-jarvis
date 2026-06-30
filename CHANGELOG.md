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

### Changed
- **Doctrine — adaptation au contexte de chaque conversation.** Ajout dans `CLAUDE.md`
  (system prompt runtime) d'une règle cardinale : la sortie est **cloisonnée par
  conversation** (jamais de monitoring infra dans une conversation dédiée ; coaching
  spécifique au contexte de la conversation), tandis que le savoir reste **mutualisé**
  via `global/state` (vue d'ensemble, corrélation inter-conversations). Pérenne par
  construction : re-seedée à chaque déploiement par `docker/seed_merge.py`.
