"""Bounded shopping supervisor and discovery-agent graph for run type 012."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI

from life_agent.core.config import Settings
from life_agent.core.llm.deepseek import (
    LLMRequestError,
    create_deepseek_completion,
    open_deepseek_client,
)
from life_agent.core.llm.tool_loop import ToolLoopResult, run_tool_loop
from life_agent.tools.mcp import McpClient

DECISIONS = {"direct_answer", "clarification", "delegated_discovery"}
MAX_DELEGATIONS = 1


@dataclass(frozen=True)
class ShoppingAgentResult:
    answer: str
    decision_type: str
    delegated: bool
    mcp_call_count: int
    source: dict[str, object]


class _ShoppingState(TypedDict, total=False):
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


def _delegate_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "delegate_shopping_discovery",
            "description": (
                "委派信息发现 Agent 查询商品候选。仅当查询商品候选能帮助回答当前购物目标时使用；"
                "缺预算不阻止只读查询。不要用于普通聊天、条件不明且必须先追问的情况。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "minLength": 1, "maxLength": 120},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
    }


_DECISION_CORRECTION = (
    "请只返回一个 JSON 对象，不要 Markdown 代码块或额外说明："
    '{"decision_type":"direct_answer|clarification|delegated_discovery","answer":"..."}。'
    "如果需要查询商品候选，请改用委派工具调用。"
)


def _extract_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating code fences, prose, or trailing noise."""
    text = content.strip()
    candidates = [text]
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            candidates.append("\n".join(lines[1:-1]))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LLMRequestError("主 Agent 返回的决策不是有效 JSON。")


def _parse_decision(content: str | None) -> tuple[str, str]:
    if not content or not content.strip():
        raise LLMRequestError("主 Agent 返回空响应。")
    value = _extract_json_object(content)
    decision = value.get("decision_type")
    answer = value.get("answer")
    if decision not in DECISIONS or not isinstance(answer, str) or not answer.strip():
        raise LLMRequestError("主 Agent 返回了无效的决策结构。")
    return decision, answer.strip()


def _bounded_json(value: object) -> object:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > 12_000:
            return {"truncated": True, "text": encoded[:12_000]}
        return json.loads(encoded)
    except (TypeError, ValueError):
        return {"text": str(value)[:12_000], "truncated": True}


def _supervisor_messages(goal: str, conditions: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是购物主 Agent。只处理当前购物目标和已确认条件。必须选择 direct_answer、"
                "clarification 或 delegated_discovery。缺少关键目标时追问；查询商品候选有价值时只用"
                "delegate_shopping_discovery 委派信息发现 Agent。不得编造预算、数量、报价或查询事实。"
                "如果不委派，返回 JSON：{\"decision_type\":...,\"answer\":...}。"
            ),
        },
        {
            "role": "user",
            "content": f"购物目标：{goal}\n已知条件：{json.dumps(dict(conditions), ensure_ascii=False)}",
        },
    ]


def _decision_from_message(
    message: Any,
) -> tuple[str, str, dict[str, object] | None]:
    calls = list(message.tool_calls or [])
    if len(calls) > 1:
        raise LLMRequestError("主 Agent 返回多个委派，超过一次委派上限。")
    if calls:
        call = calls[0]
        if call.function.name != "delegate_shopping_discovery":
            raise LLMRequestError("主 Agent 请求了未知委派能力。")
        try:
            request = json.loads(call.function.arguments)
        except json.JSONDecodeError as exc:
            raise LLMRequestError("主 Agent 委派参数不是有效 JSON。") from exc
        if not isinstance(request, dict) or not isinstance(request.get("keyword"), str):
            raise LLMRequestError("主 Agent 委派参数无效。")
        limit = request.get("limit", 5)
        if not isinstance(limit, int) or not 1 <= limit <= 10:
            raise LLMRequestError("主 Agent 委派数量超出限制。")
        return "delegated_discovery", "", {"keyword": request["keyword"], "limit": limit}
    decision, answer = _parse_decision(message.content)
    return decision, answer, None


async def _supervisor_decide(
    settings: Settings,
    goal: str,
    conditions: dict[str, object],
    model_client: AsyncOpenAI | None,
) -> tuple[str, str, dict[str, object] | None, int]:
    """Decide once; retry the JSON contract at most once when formatting fails."""
    messages = _supervisor_messages(goal, conditions)
    tools = [_delegate_tool()]
    async with open_deepseek_client(settings, model_client) as client:
        response = await create_deepseek_completion(
            settings,
            client,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=256,
        )
        if not response.choices:
            raise LLMRequestError("主 Agent 返回空响应。")
        message = response.choices[0].message
        if message.tool_calls:
            decision, answer, request = _decision_from_message(message)
            return decision, answer, request, 1
        try:
            decision, answer = _parse_decision(message.content)
            return decision, answer, None, 1
        except LLMRequestError:
            retry_messages = [
                *messages,
                {"role": "assistant", "content": message.content or ""},
                {"role": "user", "content": _DECISION_CORRECTION},
            ]
            retry = await create_deepseek_completion(
                settings,
                client,
                messages=retry_messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=256,
            )
    if not retry.choices:
        raise LLMRequestError("主 Agent 纠正后仍返回空响应。")
    decision, answer, request = _decision_from_message(retry.choices[0].message)
    return decision, answer, request, 2


async def _summarize_discovery(
    settings: Settings,
    goal: str,
    discovery: ToolLoopResult,
    model_client: AsyncOpenAI | None,
) -> str:
    evidence = {
        "called": discovery.tool_calls == 1,
        "service": discovery.service_id,
        "tool": discovery.called_tool,
        "simulated": True,
        "result": discovery.tool_result,
    }
    messages = [
        {
            "role": "system",
            "content": "你是购物主 Agent，只根据受限的信息发现证据生成用户可读回复；模拟数据必须明确标注，错误不得伪装成空结果。",
        },
        {
            "role": "user",
            "content": f"目标：{goal}\n发现证据：{json.dumps(evidence, ensure_ascii=False)}",
        },
    ]
    async with open_deepseek_client(settings, model_client) as client:
        response = await create_deepseek_completion(
            settings, client, messages=messages, max_tokens=256
        )
    if not response.choices or not (response.choices[0].message.content or "").strip():
        raise LLMRequestError("主 Agent 汇总返回空响应。")
    return response.choices[0].message.content.strip()


def _build_graph(
    settings: Settings,
    model_client: AsyncOpenAI | None,
    discovery_model_client: AsyncOpenAI | None,
    mcp_client: McpClient | Any | None,
    *,
    force_discovery: bool = False,
):
    async def supervisor(state: _ShoppingState) -> dict[str, object]:
        if force_discovery:
            # The trusted capability router already selected product discovery.
            # Skip a second model decision but keep the same graph delegation edge.
            return {
                "decision_type": "delegated_discovery",
                "delegated": True,
                "answer": "",
                "discovery_request": {"limit": 5},
                "supervisor_requests": 0,
            }
        decision, answer, request, requests = await _supervisor_decide(
            settings, state["goal"], state["conditions"], model_client
        )
        return {
            "decision_type": decision,
            "delegated": decision == "delegated_discovery",
            "answer": answer,
            "discovery_request": request or {},
            "supervisor_requests": requests,
        }

    async def discovery(state: _ShoppingState) -> dict[str, object]:
        request = state["discovery_request"]
        keyword = request.get("keyword")
        keyword_instruction = (
            f"必要查询关键词：{keyword}\n"
            if keyword
            else (
                "请从购物目标中提取一个简短商品关键词后调用工具；"
                "关键词只写商品名称（2–10 个汉字，例如“奖品”“文具”“水杯”），"
                "不要包含城市、地点、预算、人数或整句。\n"
            )
        )
        prompt = (
            f"购物目标：{state['goal']}\n{keyword_instruction}"
            f"已知条件：{json.dumps(state['conditions'], ensure_ascii=False)}\n"
            f"最多返回 {request.get('limit', 5)} 个候选。"
        )
        result = await run_tool_loop(
            settings,
            prompt,
            service_id="shopping",
            allowed_tool_names=("search_products",),
            model_client=discovery_model_client,
            mcp_client=mcp_client,
            total_timeout_seconds=90.0,
            force_tool_call=force_discovery,
        )
        return {"discovery": result, "mcp_call_count": result.tool_calls}

    async def finalize(state: _ShoppingState) -> dict[str, object]:
        supervisor_requests = int(state.get("supervisor_requests", 1))
        if state["decision_type"] != "delegated_discovery":
            return {
                "source": {
                    "simulated": False,
                    "model_requests": supervisor_requests,
                },
                "mcp_call_count": 0,
            }
        discovery_result = cast(ToolLoopResult, state["discovery"])
        answer = await _summarize_discovery(
            settings, state["goal"], discovery_result, model_client
        )
        return {
            "answer": answer,
            "source": {
                "service_id": discovery_result.service_id,
                "tool": discovery_result.called_tool,
                "simulated": True,
                "tool_result": _bounded_json(discovery_result.tool_result),
                "model_requests": (
                    supervisor_requests + discovery_result.model_requests + 1
                ),
                "tool_calls": discovery_result.tool_calls,
            },
        }

    graph = StateGraph(_ShoppingState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("discovery", discovery)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: "discovery" if state["decision_type"] == "delegated_discovery" else "finalize",
        {"discovery": "discovery", "finalize": "finalize"},
    )
    graph.add_edge("discovery", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_shopping_agent(
    settings: Settings,
    goal: str,
    conditions: dict[str, object],
    *,
    model_client: AsyncOpenAI | None = None,
    discovery_model_client: AsyncOpenAI | None = None,
    mcp_client: McpClient | Any | None = None,
    force_discovery: bool = False,
) -> ShoppingAgentResult:
    """Run one bounded supervisor/discovery graph without a checkpointer."""
    if not goal.strip():
        raise LLMRequestError("购物目标不能为空。")
    result = await _build_graph(
        settings,
        model_client,
        discovery_model_client,
        mcp_client,
        force_discovery=force_discovery,
    ).ainvoke({"goal": goal, "conditions": dict(conditions)})
    decision = str(result["decision_type"])
    return ShoppingAgentResult(
        answer=str(result["answer"]),
        decision_type=decision,
        delegated=decision == "delegated_discovery",
        mcp_call_count=int(result.get("mcp_call_count", 0)),
        source=dict(result.get("source", {})),
    )
