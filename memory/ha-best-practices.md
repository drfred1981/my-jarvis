# Home Assistant Best Practices

Source: https://github.com/homeassistant-ai/skills/blob/main/skills/home-assistant-best-practices

**Principe : utiliser les constructions natives HA autant que possible.** Les templates contournent la validation, échouent silencieusement, et rendent le debug opaque.

## Workflow de décision

1. **Refactoring ?** → Lire la section safe-refactoring avant tout
2. **Vérifier s'il existe une condition/trigger native** avant d'écrire un template
3. **Vérifier s'il existe un helper intégré** avant de créer un template sensor
4. **Choisir le bon mode d'automation** (single/restart/queued/parallel)
5. **Utiliser entity_id** au lieu de device_id (sauf Z2M autodiscovered)
6. **Boutons Zigbee** : ZHA → event trigger + device_ieee ; Z2M → device ou mqtt trigger

## Conditions natives (au lieu de templates)

| Template évitable | Alternative native |
|---|---|
| `{{ states('x') \| float > 25 }}` | `condition: numeric_state` avec `above: 25` |
| `{{ is_state('x', 'on') and is_state('y', 'on') }}` | `condition: and` avec state conditions |
| `{{ now().hour >= 9 }}` | `condition: time` avec `after: "09:00:00"` |
| `wait_template: "{{ is_state(...) }}"` | `wait_for_trigger` avec state trigger |
| `{{ states('x') in ['a', 'b'] }}` | `condition: state` avec `state: ["a", "b"]` |

### Types de conditions natives
- **state** : état, multiple états (OR), attribut, durée (for)
- **numeric_state** : above/below/range, attribut numérique
- **time** : plage horaire (gère minuit), jours de semaine
- **sun** : before/after sunrise/sunset avec offset
- **zone** : présence dans une zone
- **and/or/not** : combinaison logique

## Modes d'automation

| Scénario | Mode |
|----------|------|
| Lumière mouvement avec timeout | `restart` |
| Traitement séquentiel (serrures) | `queued` |
| Actions indépendantes par entité | `parallel` |
| Notifications one-shot | `single` |

## Wait actions

- **`wait_for_trigger`** (préféré) : event-driven, attend un **changement**
- **`wait_template`** : polling, passe immédiatement si déjà vrai
- Les deux exposent `wait.completed` et `wait.remaining`

## Helpers intégrés (au lieu de template sensors)

| Besoin | Helper | Pas template |
|--------|--------|-------------|
| Moyenne/somme de capteurs | `min_max` | Template avec math |
| Moyenne dans le temps | `statistics` | Template tracking |
| Taux de variation | `derivative` | Template delta |
| On/off au seuil | `threshold` (avec hystérésis) | Template binary sensor |
| Consommation par période | `utility_meter` | Counter + reset |
| Temps dans un état | `history_stats` | Template timestamps |
| Puissance → énergie | `integration` (Riemann) | Template approximation |
| Planning hebdo | `schedule` | Template weekday |
| Période de la journée | `tod` (time of day) | Template time |
| Any-on / All-on | `group` | Template binary sensor |

## Contrôle des appareils

### Structure service call moderne
```yaml
action:
  - action: domain.service
    target:
      entity_id: entity.id    # Stable (recommandé)
      area_id: area_name       # Stable
      # device_id: xxx         # Éviter sauf Z2M
    data:
      parameter: value
```

### entity_id vs device_id
- `device_id` change quand l'appareil est ré-ajouté → **automations cassées silencieusement**
- `entity_id` est contrôlable, stable, renommable
- Exception : Z2M device triggers autodiscovered, ou device-only triggers

### Boutons Zigbee
- **ZHA** : `event` trigger avec `device_ieee` (persistant)
- **Z2M** : `device` trigger (autodiscovered) ou `mqtt` trigger

## Templates : quand c'est OK

Templates appropriés pour :
1. Données dynamiques dans service calls (brightness, messages)
2. Messages de notification dynamiques
3. Traitement de données brutes (MQTT, REST)
4. Accès au contexte trigger (`trigger.to_state`, etc.)
5. Formatage de strings complexes
6. Extraction d'attributs
7. État conditionnel complexe multi-facteurs
8. Itération sur entités
9. Calculs date/heure

### Bonnes pratiques templates
- Toujours `unique_id` pour les template sensors
- Toujours définir `availability`
- Utiliser `states('entity')` pas `states.sensor.x.state`
- Conversion safe : `| float(0)`, `| int(-1)`, `| default('N/A')`
- Vérifier : `has_value('entity')` avant utilisation
- `state_attr()` avec `| default()`
- Templates trigger-based pour efficacité (ne s'exécutent que sur changement)

## if/then vs choose

- **if/then/else** : condition binaire simple
- **choose** : branches multiples (switch/case) avec trigger IDs

## Trigger IDs

Assigner des IDs aux triggers pour conditions et choose :
```yaml
trigger:
  - trigger: state
    entity_id: binary_sensor.motion
    to: "on"
    id: "motion_on"
```
Accès : `trigger.id`, `trigger.entity_id`, `trigger.to_state`

## Safe Refactoring

Workflow obligatoire pour toute modification de config existante :

1. **Identifier le scope** : qu'est-ce qui change, entités siblings du device
2. **Chercher TOUS les consommateurs** : automations, dashboards, scripts, scenes, AppDaemon, Node-RED
3. **Faire le changement**
4. **Mettre à jour chaque consommateur**
5. **Vérifier** : chercher l'ancien identifiant (0 résultats attendus), confirmer le nouveau

### Renommage d'entités
- Découvrir les siblings du device (switch, sensor, update, etc.)
- Renommer tous les siblings de manière cohérente
- Chercher dans tap_action, hold_action, conditional cards, templates Jinja2

### Remplacement helper
- Le helper crée un nouveau entity_id → mettre à jour tous les consommateurs
- Tester l'équivalence de valeurs, unités, précision

### Restructuration triggers
- `wait_for_trigger` attend un **changement** ; `wait_template` vérifie l'**état courant**
- Chercher les automations qui appellent via `automation.trigger`
