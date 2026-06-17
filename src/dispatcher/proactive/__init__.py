"""Proactive scheduling — two tracks.

- `monitor`      : Track A — infra health checks, firm cadence floor, pause-on-alert.
- `introspector` : Track B — autonomous introspection with deterministic exponential
                   backoff keyed on chat activity, night-mode suppression, coaching.
- `quiet`        : shared night-mode (quiet hours) helpers.
- `prompts`      : introspection prompt templates (content / "worth saying?" lives here).

Import submodules directly (e.g. ``from proactive.monitor import Monitor``) to keep
this package's __init__ side-effect-free and cycle-safe.
"""
