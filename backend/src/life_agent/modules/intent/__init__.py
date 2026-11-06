"""Single, model-assisted entry point for conversation intent recognition."""

from .service import classify_conversation_turn

__all__ = ["classify_conversation_turn"]
