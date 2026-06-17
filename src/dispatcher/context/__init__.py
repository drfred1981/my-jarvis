"""Context injection — prepend distilled local + global context to a message.

`injector` reads the same memory NFS store the `memory` MCP writes to, so a
conversation benefits from its per-conversation context and the global perimeter
without spending a tool call each turn.
"""

from .injector import build_block, inject, local_context_name

__all__ = ["build_block", "inject", "local_context_name"]
