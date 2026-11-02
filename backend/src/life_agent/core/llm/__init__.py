"""Minimal language-model integration used by local checks and future workers."""

from life_agent.core.llm.deepseek import (
    LLMConfigurationError,
    LLMRequestError,
    LLMResult,
    call_deepseek,
)

__all__ = [
    "LLMConfigurationError",
    "LLMRequestError",
    "LLMResult",
    "call_deepseek",
]