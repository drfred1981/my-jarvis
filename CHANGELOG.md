# Changelog

Toutes les évolutions notables de Jarvis. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [Non publié]

### Changed
- **Doctrine — adaptation au contexte de chaque conversation.** Ajout dans `CLAUDE.md`
  (system prompt runtime) d'une règle cardinale : la sortie est **cloisonnée par
  conversation** (jamais de monitoring infra dans une conversation dédiée ; coaching
  spécifique au contexte de la conversation), tandis que le savoir reste **mutualisé**
  via `global/state` (vue d'ensemble, corrélation inter-conversations). Pérenne par
  construction : re-seedée à chaque déploiement par `docker/seed_merge.py`.
