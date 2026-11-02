"""Verify one configured MCP service through discovery and a real tool call."""

import argparse
import asyncio
from collections.abc import Sequence
from typing import Any

from life_agent.core.config import get_settings
from life_agent.tools.mcp import McpClient, McpClientError

EXPECTED_TOOL = "search_products"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, help="受信配置中的 MCP 服务 ID")
    return parser.parse_args()


def validate_mock_result(value: Any) -> tuple[int, str]:
    if not isinstance(value, dict):
        raise TypeError("工具未返回结构化对象。")
    if value.get("source_type") != "mock":
        raise ValueError("工具结果缺少 source_type=mock。")
    if value.get("source_service") != "shopping-mcp":
        raise ValueError("工具结果缺少预期的模拟来源服务。")
    products = value.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("模拟查询未返回候选商品。")
    return len(products), str(products[0].get("name", ""))


async def check_mcp(service_id: str) -> int:
    print(f"服务 ID: {service_id}")
    try:
        async with McpClient(get_settings()).connect(service_id) as connection:
            tools = await connection.list_tools()
            tool_names = [tool.name for tool in tools]
            print(f"协议版本: {connection.protocol_version}")
            if connection.server_info is not None:
                print(
                    "服务端: "
                    f"{connection.server_info.name} {connection.server_info.version}"
                )
            print(f"发现工具: {', '.join(tool_names) or '无'}")
            if EXPECTED_TOOL not in tool_names:
                raise ValueError(f"未发现预期工具 {EXPECTED_TOOL}。")

            call = await connection.call_tool(
                EXPECTED_TOOL,
                {"keyword": "笔", "max_price": 15, "limit": 2},
            )
            count, first_name = validate_mock_result(call.result.structured_content)
            print(f"查询摘要: {count} 个模拟候选，首项名称={first_name}")
            print("状态: 成功")
            return 0
    except (McpClientError, TypeError, ValueError) as exc:
        print(f"失败: {exc}")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args() if argv is None else parse_args_from(argv)
    return asyncio.run(check_mcp(args.service))


def parse_args_from(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, help="受信配置中的 MCP 服务 ID")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())