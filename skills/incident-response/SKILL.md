---
name: incident-response
description: Investigate a homelab production incident end-to-end (root cause, blast radius, remediation, Planka tracking). Use when the user mentions a pod CrashLoop, an outage, a service down, a Longhorn volume faulted, postgres unavailable, or any phrase like "regarde ce qu'il se passe sur X" / "X est cassé" / "ça plante".
tools: kubernetes, fluxcd, grafana-prometheus, alertmanager, gatus, planka, memory, git
---

# Incident response

## Decision tree

1. **Triage** (≤ 2 min)
   - `kubernetes.list_pods` on the affected namespace; `get_events` filtered to Warning.
   - `gatus.get_health` for an external view; `alertmanager.list_alerts` for active alerts.
   - State the impact in one sentence ("X est down, conséquence Y").

2. **Root cause** (≤ 10 min)
   - Trace **upstream** dependencies: a CrashLoop on app A often points to DB/Kafka/NFS upstream.
   - Cross-check Prometheus alerts, node DiskPressure/Memory, FluxCD reconciliation, recent commits in `apps-in-k8s`.
   - Document hypotheses + evidence in `memory.append_to_context("incidents/<YYYY-MM-DD>-<short-id>", …)`.

3. **Remediation** — always **read-only first**, then **propose**, then **ask** before destructive.
   - Salvage / scale / restart / failover — describe blast radius before acting.
   - When the user authorizes, apply, then verify with the same probes used in step 1.

4. **Track in Planka** (MCO project)
   - Create a card in "Fait" if resolved instantly, or in "À faire" otherwise.
   - Description: contexte, symptômes, cause racine, actions réalisées/proposées, commits associés.
   - Add a comment for each significant step.

5. **Persist learning**
   - `memory.append_to_context("incidents/recurring", …)` if the pattern is recurrent.
   - Update the relevant app context (`apps/<app>.md`) with the workaround or a permanent fix link.

## Critical reflexes

- Never `kubectl delete pvc` / `--force` without explicit user authorization.
- Longhorn volume `faulted` + single replica = use the salvage procedure in `memory.load_context("cluster/longhorn-salvage")` (reset `failedAt` on the replica via `kubectl patch`).
- Postgres CNPG `Unknown` for hours = the underlying volume is detached; fix volume first, then `kubectl delete pod` to force reschedule.

## Tone

Concise. State **what** is broken, **why**, **what you propose**. Three short sections beats one long paragraph.
