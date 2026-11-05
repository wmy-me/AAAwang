"""Pure graph-node helpers for the bounded discovery workflow."""

from typing import Any


def delegate_tool() -> dict[str, Any]:
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
