"""State and result contracts for the bounded discovery graph."""

from typing import TypedDict

from life_agent.core.llm.tool_loop import ToolLoopResult


class DiscoveryState(TypedDict, total=False):
    goal: str
    conditions: dict[str, object]
    decision_type: str
    delegated: bool
    discovery_request: dict[str, object]
    discovery: ToolLoopResult
    answer: str
    source: dict[str, object]
    supervisor_requests: int
    mcp_call_count: int
