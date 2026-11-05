"""One bounded language-model to MCP tool-call round trip."""

import asyncio
import hashlib
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import SchemaError, ValidationError, validate
from openai import AsyncOpenAI

from life_agent.core.budget import RunBudget
from life_agent.core.config import Settings
from life_agent.core.llm.deepseek import (
    LLMRequestError,
    create_deepseek_completion,
    open_deepseek_client,
)
from life_agent.tools.mcp import DiscoveredTool, McpClient

MAX_TOOL_RESULT_CHARS = 12_000
MODEL_TOOL_NAME_LIMIT = 64


class ToolLoopError(RuntimeError):
    """Raised when the bounded tool loop cannot continue safely."""


@dataclass(frozen=True)
class ToolLoopResult:
    """Auditable result of at most two model requests and one MCP call."""

    answer: str
    model_called_tool: bool
    service_id: str
    protocol_version: str
    discovered_tools: tuple[str, ...]
    called_tool: str | None = None
    tool_result: Any = None
    model_requests: int = 1
    tool_calls: int = 0


@dataclass(frozen=True)
class _ExposedTool:
    discovered: DiscoveredTool
    model_name: str


def _model_tool_name(qualified_name: str) -> str:
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]", "_", qualified_name)
    digest = hashlib.sha256(qualified_name.encode()).hexdigest()[:10]
    prefix_limit = MODEL_TOOL_NAME_LIMIT - len(digest) - 1
    return f"{safe_prefix[:prefix_limit]}_{digest}"


def _expose_tools(
    tools: list[DiscoveredTool], allowed_tool_names: Collection[str]
) -> tuple[list[dict[str, Any]], dict[str, _ExposedTool]]:
    allowed = set(allowed_tool_names)
    exposed: list[dict[str, Any]] = []
    mapping: dict[str, _ExposedTool] = {}
    for tool in tools:
        if tool.name not in allowed:
            continue
        model_name = _model_tool_name(tool.qualified_name)
        if model_name in mapping:
            raise ToolLoopError("模型工具名发生冲突，已停止执行。")
        exposed_tool = _ExposedTool(tool, model_name)
        mapping[model_name] = exposed_tool
        exposed.append(
            {
                "type": "function",
                "function": {
                    "name": model_name,
                    "description": tool.tool.description or tool.qualified_name,
                    "parameters": tool.tool.input_schema,
                },
            }
        )
    if not exposed:
        raise ToolLoopError("所选 MCP 服务没有发现允许调用的工具。")
    return exposed, mapping


def _parse_arguments(arguments: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ToolLoopError("模型返回的工具参数不是有效 JSON，未执行工具。") from exc
    if not isinstance(value, dict):
        raise ToolLoopError("模型返回的工具参数不是对象，未执行工具。")
    try:
        validate(instance=value, schema=dict(schema))
    except SchemaError as exc:
        raise ToolLoopError("MCP 工具公布了无效的输入 schema，未执行工具。") from exc
    except ValidationError as exc:
        raise ToolLoopError("模型工具参数不符合 MCP 输入 schema，未执行工具。") from exc
    return value


def _tool_result_json(value: Any) -> str:
    try:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ToolLoopError("MCP 工具结果无法安全序列化给模型。") from exc
    if len(serialized) > MAX_TOOL_RESULT_CHARS:
        raise ToolLoopError("MCP 工具结果超过模型回传上限。")
    return serialized


async def run_tool_loop(
    settings: Settings,
    prompt: str,
    *,
    service_id: str,
    allowed_tool_names: Collection[str],
    model_client: AsyncOpenAI | None = None,
    mcp_client: McpClient | None = None,
    total_timeout_seconds: float = 90.0,
    force_tool_call: bool = False,
    budget: RunBudget | None = None,
    system_prompt: str | None = None,
) -> ToolLoopResult:
    """Run one discovery, up to two model requests, and at most one MCP call."""
    if not prompt.strip():
        raise ToolLoopError("问题不能为空。")
    if total_timeout_seconds <= 0:
        raise ToolLoopError("工具循环总超时必须大于 0。")

    async def execute() -> ToolLoopResult:
        active_mcp_client = mcp_client or McpClient(settings)
        async with active_mcp_client.connect(service_id) as connection:
            discovered = await connection.list_tools()
            model_tools, mapping = _expose_tools(discovered, allowed_tool_names)
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": system_prompt
                    or (
                        "仅依据工具结果回答商品问题。工具数据均为模拟数据，"
                        "回答必须明确说明商品和价格是模拟信息，不得补充工具未返回的候选。"
                    ),
                },
                {"role": "user", "content": prompt},
            ]

            async with open_deepseek_client(settings, model_client) as active_model:
                first = await create_deepseek_completion(
                    settings,
                    active_model,
                    budget=budget,
                    messages=messages,
                    tools=model_tools,
                    tool_choice="required" if force_tool_call else "auto",
                    parallel_tool_calls=False if force_tool_call else None,
                    max_tokens=256,
                )
                if not first.choices:
                    raise LLMRequestError("DeepSeek 返回空响应：没有候选结果。")
                message = first.choices[0].message
                tool_calls = list(message.tool_calls or [])
                if not tool_calls:
                    if force_tool_call:
                        raise ToolLoopError("模型未返回必需的工具调用，已停止执行。")
                    answer = (message.content or "").strip()
                    if not answer:
                        raise LLMRequestError("DeepSeek 返回空响应：没有文本或工具调用。")
                    return ToolLoopResult(
                        answer=answer,
                        model_called_tool=False,
                        service_id=service_id,
                        protocol_version=connection.protocol_version,
                        discovered_tools=tuple(tool.qualified_name for tool in discovered),
                    )
                if len(tool_calls) != 1:
                    if not force_tool_call:
                        raise ToolLoopError("模型返回多个工具调用，超过本轮一次调用上限。")
                    tool_calls = tool_calls[:1]

                tool_call = tool_calls[0]
                exposed = mapping.get(tool_call.function.name)
                if exposed is None:
                    raise ToolLoopError("模型请求了未知或未授权工具，未执行工具。")
                arguments = _parse_arguments(
                    tool_call.function.arguments, exposed.discovered.tool.input_schema
                )
                if budget is not None:
                    budget.reserve("mcp")
                call_result = await connection.call_tool(
                    exposed.discovered.name, arguments
                )
                structured = call_result.result.structured_content
                tool_payload = structured
                if tool_payload is None:
                    tool_payload = {
                        "content": [
                            item.model_dump(mode="json")
                            for item in call_result.result.content
                        ]
                    }
                serialized_result = _tool_result_json(tool_payload)
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "content": message.content,
                            "tool_calls": [
                                {
                                    "id": tool_call.id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_call.function.name,
                                        "arguments": tool_call.function.arguments,
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": serialized_result,
                        },
                    ]
                )
                final = await create_deepseek_completion(
                    settings,
                    active_model,
                    budget=budget,
                    messages=messages,
                    max_tokens=256,
                )
                if not final.choices:
                    raise LLMRequestError("DeepSeek 返回空响应：没有最终候选结果。")
                final_message = final.choices[0].message
                if final_message.tool_calls:
                    raise ToolLoopError("模型在最终回复中再次请求工具，超过调用上限。")
                answer = (final_message.content or "").strip()
                if not answer:
                    raise LLMRequestError("DeepSeek 返回空响应：没有最终文本内容。")
                return ToolLoopResult(
                    answer=answer,
                    model_called_tool=True,
                    service_id=service_id,
                    protocol_version=connection.protocol_version,
                    discovered_tools=tuple(tool.qualified_name for tool in discovered),
                    called_tool=exposed.discovered.qualified_name,
                    tool_result=tool_payload,
                    model_requests=2,
                    tool_calls=1,
                )

    try:
        async with asyncio.timeout(total_timeout_seconds):
            return await execute()
    except TimeoutError as exc:
        raise ToolLoopError(
            f"工具循环在 {total_timeout_seconds:g} 秒总截止时间内未完成。"
        ) from exc