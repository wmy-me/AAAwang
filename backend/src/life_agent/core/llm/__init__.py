"""Minimal language-model integration used by local checks and future workers."""

from life_agent.core.llm.deepseek import (
    LLMConfigurationError,
    LLMRequestError,
    LLMResult,
    call_deepseek,
)
from life_agent.core.llm.tool_loop import ToolLoopError, ToolLoopResult, run_tool_loop

__all__ = [
    "LLMConfigurationError",
    "LLMRequestError",
    "LLMResult",
    "ToolLoopError",
    "ToolLoopResult",
    "call_deepseek",
    "run_tool_loop",
]