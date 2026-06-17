"""Conversation identity & durable registry.

- `keys`     : build/parse structured conversation keys (discord:dm:…, etc.)
- `registry` : file-backed map key → Claude session id + activity metadata,
               so `--resume` continuity and idle tracking survive restarts.
"""

from .registry import Conversation, ConversationRegistry

__all__ = ["Conversation", "ConversationRegistry"]
