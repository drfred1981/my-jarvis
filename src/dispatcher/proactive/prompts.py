"""Introspection prompt templates (Track B).

The *cadence* (when to wake, how deep) is owned by the code (`introspector`).
These prompts own the *content* and the "worth saying?" judgment. Each must reply
exactly ``RAS`` when nothing is worth surfacing, so the scheduler stays silent.
"""

# Sentinel an introspection prompt returns when there's nothing to say.
CLEAR = "RAS"

LIGHT = (
    "Check de présence léger (introspection automatique). "
    "Y a-t-il un blocage évident ou une urgence visible côté chat ou projets ? "
    "Si rien ne mérite l'attention, réponds EXACTEMENT 'RAS'. "
    "Sinon une seule phrase, priorisée."
)

MEDIUM = (
    "Revue intermédiaire (introspection automatique). "
    "Scanne l'activité récente (conversations, cartes Planka en cours, alertes) et "
    "compare à ce que tu sais déjà (mémoire `global/state` via load_context). "
    "Mets à jour `global/state` (save_context) si l'état a bougé. "
    "Ne remonte (revue de périmètre, digest opérateur) que ce qui mérite l'attention ; "
    "sinon EXACTEMENT 'RAS'."
)

DEEP = (
    "Revue de domaine complète (introspection automatique, cycle profond). "
    "1. Passe en revue : projets/cartes Planka, infra (cluster/Flux), repos git. "
    "2. Compare avec la mémoire `global/state` (load_context) puis mets-la à jour "
    "   (save_context) avec l'état synthétique courant de tout le périmètre. "
    "3. Auto-introspection : un skill te manque-t-il ? un comportement à corriger ? "
    "   une donnée que tu pourrais obtenir autrement ? Note-le dans `global/state`. "
    "4. Si quelque chose mérite une remontée en revue de périmètre (digest opérateur), "
    "   formule-le clairement ; sinon réponds EXACTEMENT 'RAS'."
)

# Per-conversation coaching, run inside that conversation's own context, in the
# `coach` posture (accompaniment) — NOT a generic proactive ping. The intervention
# bar and the lowest-effective-level rule keep the signal worth reading.
COACH = (
    "Posture coach (cf. skill `coach`), dans le contexte de CETTE conversation. "
    "Au vu de ce que tu maintiens pour elle (objectifs, état, ÉCART objectif−état, "
    "historique, refus/préférences), y a-t-il MAINTENANT une intervention spontanée "
    "dont la valeur dépasse NETTEMENT le coût d'interruption, avec une confiance suffisante ? "
    "Si oui : choisis le PLUS BAS niveau de l'échelle qui fait le travail (noter → question "
    "légère → suggestion → proposition argumentée), formule-la courte et actionnable, et ne "
    "re-propose JAMAIS ce qui a déjà été écarté. "
    "Sinon réponds EXACTEMENT 'RAS'. Si tu apprends un fait durable (objectif, refus, "
    "préférence), persiste-le via `memory:save_context` dans la mémoire locale de la conversation."
)


def for_depth(depth: str) -> str:
    """Return the introspection prompt for a depth ('light' | 'medium' | 'deep')."""
    return {"light": LIGHT, "medium": MEDIUM, "deep": DEEP}.get(depth, LIGHT)
