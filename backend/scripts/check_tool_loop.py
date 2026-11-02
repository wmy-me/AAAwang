"""Run one real DeepSeek to MCP tool-call loop against a trusted service."""

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from life_agent.core.config import get_settings
from life_agent.core.llm import (
    LLMConfigurationError,
    LLMRequestError,
    ToolLoopError,
    run_tool_loop,
)
from life_agent.tools.mcp import McpClientError

ALLOWED_TOOLS = {"search_products"}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, help="受信配置中的 MCP 服务 ID")
    parser.add_argument("--prompt", required=True, help="本次工具调用检查的问题")
    return parser.parse_args(argv)


def validate_grounded_answer(tool_result: Any, answer: str) -> tuple[int, str]:
    if not isinstance(tool_result, Mapping):
        raise ToolLoopError("工具没有返回可核对的结构化对象。")
    if tool_result.get("source_type") != "mock":
        raise ToolLoopError("工具结果缺少 source_type=mock。")
    if tool_result.get("source_service") != "shopping-mcp":
        raise ToolLoopError("工具结果缺少预期模拟来源 shopping-mcp。")
    products = tool_result.get("products")
    if not isinstance(products, list) or not products:
        raise ToolLoopError("本次真实检查未返回可用于回答核对的模拟候选。")
    if "模拟" not in answer:
        raise ToolLoopError("最终回答没有明确标记模拟信息。")

    for product in products:
        if not isinstance(product, Mapping):
            continue
        name = str(product.get("name", ""))
        if not name or name not in answer:
            continue
        try:
            price = Decimal(str(product["unit_price"]))
        except (KeyError, InvalidOperation):
            raise ToolLoopError("工具候选缺少可核对的模拟价格。") from None
        price_forms = {str(price), format(price, "f"), format(price, ".2f")}
        if not any(price_form in answer for price_form in price_forms):
            raise ToolLoopError("最终回答中的候选缺少对应模拟价格。")
        return len(products), name
    raise ToolLoopError("最终回答没有引用实际工具返回的候选。")


async def check_tool_loop(service_id: str, prompt: str) -> int:
    settings = get_settings()
    print(f"供应商: {settings.llm_provider}")
    print(f"模型: {settings.llm_model}")
    print(f"服务 ID: {service_id}")
    try:
        result = await run_tool_loop(
            settings,
            prompt,
            service_id=service_id,
            allowed_tool_names=ALLOWED_TOOLS,
        )
        print(f"协议版本: {result.protocol_version}")
        print(f"发现工具: {', '.join(result.discovered_tools)}")
        print(f"模型发出 tool_calls: {'是' if result.model_called_tool else '否'}")
        if not result.model_called_tool or result.called_tool is None:
            raise ToolLoopError("模型没有调用工具，本次不能作为完整闭环证据。")
        count, first_name = validate_grounded_answer(result.tool_result, result.answer)
        print(f"实际调用: {result.called_tool}")
        print(f"调用计数: 模型 {result.model_requests} 次，MCP {result.tool_calls} 次")
        print(f"候选摘要: {count} 个模拟候选，已核对={first_name}")
        print(f"最终回答: {result.answer}")
        print("状态: 成功")
        return 0
    except (
        LLMConfigurationError,
        LLMRequestError,
        McpClientError,
        ToolLoopError,
    ) as exc:
        print(f"失败: {exc}")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(check_tool_loop(args.service, args.prompt))


if __name__ == "__main__":
    raise SystemExit(main())