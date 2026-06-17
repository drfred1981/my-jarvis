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
    "Ne signale (coaching équipe) que ce qui mérite l'attention ; sinon EXACTEMENT 'RAS'."
)

DEEP = (
    "Revue de domaine complète (introspection automatique, cycle profond). "
    "1. Passe en revue : projets/cartes Planka, infra (cluster/Flux), repos git. "
    "2. Compare avec la mémoire `global/state` (load_context) puis mets-la à jour "
    "   (save_context) avec l'état synthétique courant de tout le périmètre. "
    "3. Auto-introspection : un skill te manque-t-il ? un comportement à corriger ? "
    "   une donnée que tu pourrais obtenir autrement ? Note-le dans `global/state`. "
    "4. Si quelque chose mérite un coaching d'équipe, formule-le clairement ; "
    "   sinon réponds EXACTEMENT 'RAS'."
)

# Per-user proactive coaching, run inside that user's own conversation context.
USER_COACHING = (
    "Coaching individuel proactif (introspection automatique), dans le contexte de "
    "VOTRE conversation avec cet utilisateur. "
    "Y a-t-il un suivi utile, un rappel, ou un point bloquant le concernant ? "
    "Si oui, formule un message court, bienveillant et actionnable à lui adresser "
    "directement. Si rien d'utile, réponds EXACTEMENT 'RAS'."
)


def for_depth(depth: str) -> str:
    """Return the introspection prompt for a depth ('light' | 'medium' | 'deep')."""
    return {"light": LIGHT, "medium": MEDIUM, "deep": DEEP}.get(depth, LIGHT)
