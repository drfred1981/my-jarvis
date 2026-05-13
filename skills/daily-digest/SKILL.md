---
name: daily-digest
description: Produce a conversational morning brief comparing today vs yesterday across git repos, cluster state, and Planka tasks. Use when the user says "fais le récap", "ton brief", "quoi de neuf depuis hier", or when the proactive `daily-digest` monitor check is fired at 08:00.
tools: memory, git, planka, kubernetes, fluxcd, grafana-prometheus
---

# Daily morning digest

## Goal

Sound like a colleague briefing the user on arrival — **not** a status report. Short paragraphs, conversational tone, end with an open question.

## Procedure

1. **Load yesterday's brief**
   - `memory.load_context("digest/last")` to recall what you reported yesterday.
   - For each repo in `GIT_REPOS`, `memory.load_context("repos/<repo>")` to fetch the last seen HEAD SHA and branch summary.

2. **Compute diffs** (delegate to the `git` MCP server)
   - `git_log` with `since=<yesterday-08:00>` per repo.
   - Highlight: version bumps, fixes, new features, large refactors. Mention authors only if relevant.

3. **Cluster delta**
   - New / changed FluxCD reconciliations (success or failure) since yesterday.
   - Prometheus alerts that **appeared or disappeared** vs yesterday's set (saved in `cluster/last-alerts`).
   - Save current alert set to `memory.save_context("cluster/last-alerts", …)`.

4. **Planka activity**
   - Per project (MCO, Apps, Home-Assistant): cards moved, new cards, currently in "En cours".
   - Compare with `memory.load_context("planka/last-snapshot")` and refresh it.

5. **Today's watchlist** — 1 to 3 concrete things to keep an eye on.

6. **Persist** the brief you just produced:
   - `memory.save_context("digest/last", <text>)`
   - `memory.save_context("digest/YYYY-MM-DD", <text>)` (use today's real date)
   - For each repo, `memory.save_context("repos/<repo>", "HEAD=<sha>\nbranch=<name>\nlast_seen=<iso>")`.

## Output format

```
Bonjour ! Voici ce qui a bougé depuis hier matin.

**Repos** — <2-4 phrases, ne liste pas tous les commits, synthétise>

**Cluster** — <1-3 phrases sur les delta notables, ou "RAS côté infra">

**Planka** — <ce qui a bougé, ce qui t'attend en "En cours">

**À garder dans le viseur aujourd'hui** : <1-3 points concrets>

<question ouverte ou proposition d'action>
```

## Anti-patterns

- ❌ Liste exhaustive de commits ou d'alertes.
- ❌ Ton de rapport ("Bilan : …", "Statut : …").
- ❌ Reformuler ce que tu disais hier si rien n'a bougé — dis-le franchement ("rien de neuf côté X depuis hier").
- ❌ Oublier de mettre à jour la mémoire à la fin — sinon demain le diff sera erroné.
