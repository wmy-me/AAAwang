"""Trusted coordinator entry points for bounded Run decisions.

The coordinator owns the domain prompt, model-output parsing and capability
visibility decisions. Worker lifecycle, leases and terminal persistence remain
outside this module.
"""

import asyncio
import json
import logging
from typing import Any

from life_agent.agents.shared.prompt_loader import load_prompt
from life_agent.core.budget import RunBudget
from life_agent.core.llm import LLMConfigurationError, LLMRequestError, ToolLoopError
from life_agent.core.llm.deepseek import call_deepseek
from life_agent.modules.capabilities import (
    has_location_scope,
    has_weather_city,
    visible_capabilities,
)
from life_agent.tools.mcp import McpClient, McpClientError

logger = logging.getLogger(__name__)


def classify_conversation_turn(
    settings,
    content: str,
    history: list[dict[str, str]],
    tasks: list[dict[str, object]],
    budget: RunBudget | None = None,
) -> dict[str, object]:
    """Classify one conversation turn without creating a task for casual chat."""
    recent = "\n".join(
        f"{item['role']}: {item['content'][:400]}" for item in history[-8:]
    ) or "（无历史）"
    task_lines = "\n".join(
        f"- {item['id']}: {str(item.get('goal', ''))[:120]}"
        for item in tasks[:20]
    ) or "（无任务）"
    prompt = (
        "你是对话入口的受限路由器。只输出一个 JSON 对象，不要 Markdown。\n"
        '{"intent":"chat|task|update_task|ambiguous|memory","task_id":null,'
        '"clarification":null,"memory_action":null,"memory_category":null,'
        '"memory_key":null,"memory_value":null,"reason":"简短原因"}\n'
        "intent 规则：\n"
        "- chat：问候、闲聊、能力介绍、普通知识问答，不需要购物任务或工具。\n"
        "- task：用户要求购买/查询商品、地点、天气、公开网页资料，或需要调用业务能力；"
        "若明确延续某个已有任务，task_id 填其 ID，否则 task_id=null 表示新建任务。\n"
        "- update_task：用户明确修改已有任务的条件（例如“预算改为180元”）；"
        "task_id 必须指向一个已有任务。任务列表超过一个时，本轮消息必须明确提到"
        "任务名称、目标或 ID 才能选择；仅说新条件而没有指代对象时用 ambiguous。\n"
        "- ambiguous：多个任务都可能相关、指代不清或无法安全关联；"
        "填写一句自然语言 clarification，不猜任务。\n"
        "- memory：仅当用户明确要求记住、查看、修改或忘记自己的长期普通偏好时使用；"
        "memory_action 必须为 remember|list|update|forget。remember/update/forget 要提供简短英文 snake_case memory_category、"
        "中文 memory_key 和普通偏好 memory_value。不得保存或处理密码、token、密钥、证件、银行卡、支付信息、用户 ID、任务预算或一次性数量。"
        "一般聊天中的推断绝不能选择 memory。\n"
        "任务列表：\n"
        f"{task_lines}\n"
        "最近对话：\n"
        f"{recent}\n"
        f"本轮用户消息：{content}\n"
        "结合最近对话判断代词和省略：如果本轮用“那/它/那里/附近”等指代前文的地点或目标，"
        "并提出了查询/购买请求，应判定为 task；只有确实无法安全关联时才 ambiguous。"
        "只分类，不执行工具，不创建任务，不修改条件。"
    )
    try:
        response = asyncio.run(
            call_deepseek(settings, prompt, max_tokens=256, budget=budget)
        )
        value = _decision_json(response.text)
    except (LLMConfigurationError, LLMRequestError):
        logger.warning("conversation classifier unavailable; using safe local fallback")
        value = None
    if value is None:
        return _fallback_conversation_classification(content, tasks)
    intent = value.get("intent")
    if intent not in {"chat", "task", "update_task", "ambiguous", "memory"}:
        return _fallback_conversation_classification(content, tasks)
    task_id = value.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        task_id = None
    valid_ids = {str(item["id"]) for item in tasks}
    if task_id is not None and task_id not in valid_ids:
        return {
            "intent": "ambiguous",
            "task_id": None,
            "clarification": "我无法安全确定要修改哪个任务，请说明任务名称或重新描述目标。",
            "reason": "模型返回了不在当前对话中的任务 ID",
        }
    if intent == "update_task" and task_id is None:
        return {
            "intent": "ambiguous",
            "task_id": None,
            "clarification": "当前对话关联了多个任务，请说明要修改哪一个。",
            "reason": "更新意图缺少唯一任务",
        }
    clarification = value.get("clarification")
    return {
        "intent": intent,
        "task_id": task_id,
        "clarification": (
            str(clarification)[:500]
            if isinstance(clarification, str) and clarification.strip()
            else "请说明你想继续哪个任务或补充目标。"
            if intent == "ambiguous"
            else None
        ),
        "memory_action": value.get("memory_action"),
        "memory_category": value.get("memory_category"),
        "memory_key": value.get("memory_key"),
        "memory_value": value.get("memory_value"),
        "reason": str(value.get("reason"))[:500] if value.get("reason") else None,
    }


def _fallback_conversation_classification(
    content: str, tasks: list[dict[str, object]]
) -> dict[str, object]:
    """Keep chat/task behavior safe when the pre-routing model is unavailable."""
    from life_agent.modules.capabilities import RouteKind, route_task_turn

    decision = route_task_turn(content)
    if decision.kind is RouteKind.DIRECT:
        return {"intent": "chat", "task_id": None, "reason": "本地安全回退"}
    if len(tasks) > 1 and not task_words_are_new(content):
        return {
            "intent": "ambiguous",
            "task_id": None,
            "clarification": "当前对话关联了多个任务，请说明要继续哪一个。",
            "reason": "本地安全回退发现多任务歧义",
        }
    return {
        "intent": "task",
        "task_id": str(tasks[0]["id"]) if len(tasks) == 1 else None,
        "reason": "本地安全回退",
    }


def task_words_are_new(content: str) -> bool:
    return any(token in content for token in ("新任务", "另一个任务", "新建"))


def decide_capabilities(settings, claim, budget) -> dict[str, object]:
    """Ask the model for a bounded decision, then validate it server-side."""
    enabled, discovered = discover_capability_tools(settings, budget)
    visible = visible_capabilities(
        task_domain="shopping",
        enabled_services=enabled,
        discovered_tools=discovered,
    )
    capability_lines = "\n".join(
        f"- {item.capability_id}: {item.result_type}; 只读；服务={item.service_id}"
        for item in visible
    ) or "- 无可用能力"
    prompt = (
        "你是购物任务主协调 Agent。只输出一个 JSON 对象，不要 Markdown。\n"
        '{"kind":"direct|clarification|capabilities",'
        '"capability_ids":[],"clarification":null,"reason":"简短原因",'
        '"form_schema":[]}\n'
        "capability_ids 只能从下列后端授权集合中选择，不能创建新 ID、URL、服务或工具：\n"
        f"{capability_lines}\n"
        f"任务目标：{claim.goal}\n"
        f"本轮用户消息：{claim.input_message or '（无）'}\n"
        f"当前任务条件：{_bounded_json(claim.conditions)}\n"
        f"本会话近期上下文（可能已裁剪）：{getattr(claim, 'conversation_context', '') or '（无）'}\n"
        "判断规则：\n"
        "1. 问候、询问你能做什么、闲聊或解释概念：kind=direct，capability_ids=[]，不要调用工具。\n"
        "2. 用户本轮明确要查找地点/店铺/附近/路线，但没有城市或位置范围：kind=clarification。\n"
        "3. 城市名（如上海、北京）本身已是有效位置范围，不要要求区或街道；"
        "“查询上海附近的书店”应选择 map_place_search。\n"
        "4. 任务目标或本轮消息要求购买、查找或推荐具体商品（如“买彩色铅笔作为奖品”"
        "“给25人买彩色铅笔”）时，选择 shopping_product_discovery。\n"
        "5. 只有任务条件或历史目标提到预算、人数，而本轮没有商品或地点请求时，"
        "才不要选择能力。\n"
        "6. “通过动态表单确认：...” 只表示用户确认条件，不代表不得执行工具，"
        "必须同时看任务目标。任务目标明确要求购买、采购方案或生成清单且条件足够时，"
        "选择 shopping_product_discovery（目标同时要求地点时也选择地图能力）；"
        "不要因为本轮消息只有表单确认就直答。只有任务是开放探索、目标不明确"
        "或条件不足时，才可以 direct 或 clarification。\n"
        "7. 一句话包含多个目标时分别判断每个目标；form_schema 只列对当前任务确有帮助的字段，"
        "不得把地点或其他目标的信息写成商品预算、人数或数量。\n"
        "只读查询不因缺预算而阻断；无法判断时选择 direct 或 clarification，不要猜测能力。"
        "如果本轮省略城市但本会话近期上下文明确同一目标的城市/地点，可据此选择地点能力；"
        "不能凭空推测用户位置。\n"
        "form_schema 只能提出当前缺失且本轮确实有帮助的业务字段；没有必要时返回空数组。"
        "当用户明确要求通过表单收集某个具体商品或活动的偏好时，kind=clarification 也必须同时返回 form_schema；"
        "例如雨衣的颜色、面料、防水等级、帽型，或活动的地点、日期、时长，应该生成对应业务字段，"
        "不要只把这些信息写进 clarification，也不要把它们全部塞进 item。"
        "字段 id 使用简短的 snake_case 英文业务名，不得使用 owner/task/run/token/password 等身份、权限、凭据或工具字段。"
        "每项必须严格使用以下结构；id、标签、说明和选项都只是数据，不得包含 HTML、脚本或换行控制字符：\n"
        '"id":"业务字段名","control":"short_text|number|money|date|single_select|multi_select|location",'
        '"label":"简短标签","reason":"为什么需要","required":false,'
        '"unit":null,"options":[]}\n'
        "item 使用 short_text；people/quantity 使用 number 和单位 人/件；"
        "budget 使用 money 和单位 元。已确认条件不得重复提出。"
        "single_select/multi_select 必须提供 2–12 个当前需求相关且互不重复的 options；"
        "number/money 可提供 0–100000000 范围内的 min_value/max_value；其他控件不得提供 options 或数值范围。"
        "当用户明确要求补充条件或整理采购方案且关键信息缺失时，可以提出对应字段；"
        "普通只读探索不要为了补字段而阻断。"
        "budget、people、quantity 不是固定必填项。"
        "8. 本轮明确询问某个城市天气、气温或预报时，选择 weather_forecast；"
        "天气查询必须有明确城市，不能根据用户位置或任务历史猜测。"
        "9. 本轮明确询问公开网页资料、最新信息、新闻、攻略、评测、知识或目的地介绍时，"
        "若 web_search 在授权集合中可见则选择 web_search；搜索结果只是外部证据，"
        "不得把网页摘要当成已验证报价、库存或事实。"
    )
    response = asyncio.run(
        call_deepseek(
            settings,
            prompt,
            budget=budget,
            max_tokens=512,
            system_prompt=load_prompt("../coordinator/prompts/system.md"),
        )
    )
    value = _decision_json(response.text)
    if value is None:
        raise ToolLoopError("能力决策不是有效 JSON，已拒绝执行。")
    visible_ids = {item.capability_id for item in visible}
    request_text = f"{claim.goal} {claim.input_message or ''}"
    selected_ids = value.get("capability_ids", [])
    weather_request_without_selection = (
        "weather_forecast" in visible_ids
        and has_weather_city(request_text)
        and not (
            isinstance(selected_ids, list) and "weather_forecast" in selected_ids
        )
    )
    if _decision_needs_correction(value, visible_ids) or weather_request_without_selection:
        correction = (
            prompt
            + "\n上一轮输出："
            + response.text[:400]
            + "\n上一轮的 kind 与 reason/能力选择不一致。请重新输出严格 JSON；"
            "若 reason 表明需要采购能力，kind 必须是 capabilities 且 capability_ids 非空；"
            "若用户明确询问城市天气且可见集合包含 weather_forecast，必须选择 weather_forecast；"
            "否则保持 direct/clarification 并说明理由。"
        )
        response = asyncio.run(
            call_deepseek(
                settings,
                correction,
                budget=budget,
                max_tokens=512,
                system_prompt=load_prompt("../coordinator/prompts/system.md"),
            )
        )
        value = _decision_json(response.text)
        if value is None:
            raise ToolLoopError("能力决策纠正结果不是有效 JSON，已拒绝执行。")
    kind = value.get("kind")
    if kind not in {"direct", "clarification", "capabilities"}:
        raise ToolLoopError("能力决策类型未注册，已拒绝执行。")
    selected = value.get("capability_ids", [])
    if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
        raise ToolLoopError("能力决策的 capability_ids 无效。")
    if any(item not in visible_ids for item in selected) or len(set(selected)) != len(selected):
        raise ToolLoopError("模型选择了当前不可见或重复的能力。")
    if kind == "capabilities" and not selected:
        raise ToolLoopError("capabilities 决策必须选择至少一项能力。")
    if kind != "capabilities" and selected:
        # Models sometimes label a tool-using reply "direct"; capability_ids are
        # validated against the visible set, so treat them as authoritative.
        kind = "capabilities"
    context_text = getattr(claim, "conversation_context", "") or ""
    if "map_place_search" in selected and not has_location_scope(
        f"{claim.goal} {claim.input_message or ''} {context_text}"
    ):
        return {
            "kind": "clarification",
            "capability_ids": [],
            "clarification": "请先告诉我需要查询的城市或位置范围。",
            "reason": "后端校验发现地图查询缺少位置范围",
            "decision_source": "deepseek_structured_worker",
        }
    if "weather_forecast" in selected and not has_weather_city(
        f"{claim.goal} {claim.input_message or ''} {context_text}"
    ):
        return {
            "kind": "clarification",
            "capability_ids": [],
            "clarification": "请先告诉我需要查询天气的城市。",
            "reason": "后端校验发现天气查询缺少城市",
            "decision_source": "deepseek_structured_worker",
        }
    raw_clarification = value.get("clarification")
    clarification = (
        raw_clarification.strip()
        if isinstance(raw_clarification, str) and raw_clarification.strip()
        else "请补充必要信息后再试。"
    )
    return {
        "kind": kind,
        "capability_ids": selected,
        "clarification": clarification[:500] if kind == "clarification" else None,
        "reason": str(value.get("reason"))[:500] if value.get("reason") else None,
        "form_schema": value.get("form_schema", []),
        "decision_source": "deepseek_structured_worker",
    }


def validate_discovered_capabilities(
    settings, claim, budget: RunBudget | None = None
) -> None:
    """Re-discover selected services immediately before capability execution."""
    if not claim.capability_ids:
        return
    _, discovered = discover_capability_tools(settings, budget)
    visible = visible_capabilities(
        task_domain="shopping",
        enabled_services=set(discovered),
        discovered_tools=discovered,
    )
    visible_ids = {item.capability_id for item in visible}
    if any(item not in visible_ids for item in claim.capability_ids):
        raise ToolLoopError("执行前 MCP 工具发现结果已变化，能力不可用。")


def discover_capability_tools(
    settings, budget: RunBudget | None = None
) -> tuple[set[str], dict[str, dict[str, dict[str, object]]]]:
    """Discover configured MCP tools before exposing capabilities to the model."""

    async def discover() -> tuple[set[str], dict[str, dict[str, dict[str, object]]]]:
        enabled: set[str] = set()
        discovered: dict[str, dict[str, dict[str, object]]] = {}
        client = McpClient(settings)
        for service_id, service in settings.mcp_services.items():
            if not service.enabled:
                continue
            if budget is not None:
                budget.reserve("discovery")
            try:
                async with client.connect(service_id) as connection:
                    tools = await connection.list_tools()
            except McpClientError:
                logger.warning(
                    "MCP capability discovery unavailable: service=%s", service_id
                )
                continue
            enabled.add(service_id)
            discovered[service_id] = {
                tool.name: dict(tool.tool.input_schema or {}) for tool in tools
            }
        return enabled, discovered

    return asyncio.run(discover())


def _decision_json(text: str) -> dict[str, object] | None:
    """Parse one JSON object, tolerating a fenced or prose-wrapped reply."""
    stripped = text.strip()
    candidates = [stripped]
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            candidates.append("\n".join(lines[1:-1]))
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _decision_needs_correction(
    value: dict[str, object], visible_ids: set[str]
) -> bool:
    """Detect a self-contradictory model decision before executing it."""
    selected = value.get("capability_ids", [])
    if not isinstance(selected, list):
        return False
    if value.get("kind") == "capabilities" and not selected:
        return True
    if (
        value.get("kind") in {"direct", "clarification"}
        and not selected
        and "shopping_product_discovery" in visible_ids
    ):
        reason = str(value.get("reason") or "")
        return any(
            marker in reason
            for marker in (
                "应执行",
                "商品发现",
                "采购方案",
                "购买具体商品",
                "搜索商品",
                "购物能力",
                "检索候选",
                "商品查找",
            )
        )
    return False


def _bounded_json(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    return text[:12_000]
