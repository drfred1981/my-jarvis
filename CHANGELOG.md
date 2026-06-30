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
