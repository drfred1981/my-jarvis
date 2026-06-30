"""Conversation identity & durable registry.

- `keys`     : build/parse structured conversation keys (discord:dm:…, etc.)
- `registry` : file-backed map key → ConversationRecord (deterministic session
               id + description + activity), so session continuity and idle
               tracking survive restarts.
"""

from .registry import Conversation, ConversationRecord, ConversationRegistry

__all__ = ["Conversation", "ConversationRecord", "ConversationRegistry"]
