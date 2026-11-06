"""Validated conversation intent recognition, separate from capability choice."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from life_agent.core.budget import RunBudget
from life_agent.core.llm import LLMConfigurationError, LLMRequestError
from life_agent.core.llm.deepseek import call_deepseek

logger = logging.getLogger(__name__)

_INTENTS = {"chat", "task", "update_task", "ambiguous", "memory"}
_MEMORY_ACTIONS = {"remember", "list", "update", "forget"}


def classify_conversation_turn(
    settings,
    content: str,
    history: list[dict[str, str]],
    tasks: list[dict[str, object]],
    budget: RunBudget | None = None,
) -> dict[str, object]:
    """Return a bounded routing proposal; it grants neither identity nor tools."""
    recent = "\n".join(f"{item['role']}: {item['content'][:400]}" for item in history[-8:]) or "（无历史）"
    task_lines = "\n".join(f"- {item['id']}: {str(item.get('goal', ''))[:120]}" for item in tasks[:20]) or "（无任务）"
    prompt = (
        "你是对话入口的受限意图识别器。只输出一个 JSON 对象，不要 Markdown。\n"
        '{"intent":"chat|task|update_task|ambiguous|memory","task_id":null,'
        '"clarification":null,"memory_action":null,"memory_category":null,'
        '"memory_key":null,"memory_value":null,"secondary_intent":null,"reason":"简短原因"}\n'
        "intent 规则：\n"
        "- chat：问候、闲聊、能力介绍、普通知识问答，不需要业务工具。\n"
        "- task：用户要求购买/查询商品、地点、天气、公开网页资料；明确延续任务才填候选 task_id，否则为 null。\n"
        "- update_task：用户明确修改已有任务条件；task_id 必须来自任务列表。多个任务且指代不清时用 ambiguous。\n"
        "- memory：仅用户明确管理自己的长期普通偏好时使用。remember/update 需 category、key、value；"
        "forget 只需 category、key，不要求新 value；list 不要求这三个字段。不得保存密码、token、密钥、证件、银行卡、支付信息、用户 ID、任务预算或一次性数量。\n"
        "- 若一句有两个独立意图（例如记忆管理加业务查询）而当前单 Run 无法安全同时处理，"
        "填写 secondary_intent，并使用 ambiguous 和自然语言 clarification；不得静默丢弃其中之一。\n"
        "模型输出只是建议：不执行工具、不创建任务、不修改条件、不选择用户。\n"
        f"任务列表：\n{task_lines}\n最近对话：\n{recent}\n本轮用户消息：{content}\n"
        "结合近期对话理解代词和省略；无法安全关联时澄清，不猜测任务。"
    )
    try:
        response = asyncio.run(call_deepseek(settings, prompt, max_tokens=256, budget=budget))
        value = _decision_json(response.text)
    except (LLMConfigurationError, LLMRequestError):
        logger.warning("conversation intent unavailable; using safe local fallback")
        value = None
    if value is None:
        return _fallback_conversation_classification(content, tasks)
    return _validate(value, content, tasks)


def _validate(value: dict[str, object], content: str, tasks: list[dict[str, object]]) -> dict[str, object]:
    intent = value.get("intent")
    if intent not in _INTENTS:
        return _fallback_conversation_classification(content, tasks)
    if value.get("secondary_intent") not in (None, "", intent):
        return _ambiguous("这条消息同时包含多个请求。请先说明希望优先处理哪一项。")
    task_id = value.get("task_id")
    task_id = task_id if isinstance(task_id, str) and task_id else None
    valid_ids = {str(item["id"]) for item in tasks}
    if task_id is not None and task_id not in valid_ids:
        return _ambiguous("我无法安全确定要使用哪个任务，请说明任务名称或重新描述目标。")
    if intent == "update_task" and task_id is None:
        return _ambiguous("当前无法安全确定要修改哪个任务，请说明任务名称。")
    action = value.get("memory_action")
    if intent == "memory" and action not in _MEMORY_ACTIONS:
        return _ambiguous("请明确说明要记住、查看、修改或忘记哪项普通偏好。")
    if intent == "memory" and action in {"remember", "update", "forget"}:
        category = value.get("memory_category")
        key = value.get("memory_key")
        if not isinstance(category, str) or not category.strip() or not isinstance(key, str) or not key.strip():
            return _ambiguous("请说明要操作的偏好名称。")
        if action != "forget" and (not isinstance(value.get("memory_value"), str) or not str(value["memory_value"]).strip()):
            return _ambiguous("请说明这项偏好的新内容。")
    clarification = value.get("clarification")
    return {
        "intent": intent,
        "task_id": task_id,
        "clarification": str(clarification)[:500] if isinstance(clarification, str) and clarification.strip() else ("请说明你想继续哪个任务或补充目标。" if intent == "ambiguous" else None),
        "memory_action": action,
        "memory_category": value.get("memory_category"),
        "memory_key": value.get("memory_key"),
        "memory_value": value.get("memory_value"),
        "reason": str(value.get("reason"))[:500] if value.get("reason") else None,
    }


def _ambiguous(clarification: str) -> dict[str, object]:
    return {"intent": "ambiguous", "task_id": None, "clarification": clarification, "reason": "意图或归属不安全"}


def _fallback_conversation_classification(content: str, tasks: list[dict[str, object]]) -> dict[str, object]:
    """Safe fallback never synthesizes a memory mutation."""
    from life_agent.modules.capabilities import RouteKind, route_task_turn

    decision = route_task_turn(content)
    if decision.kind is RouteKind.DIRECT:
        return {"intent": "chat", "task_id": None, "reason": "本地安全回退"}
    if len(tasks) > 1 and not _task_words_are_new(content):
        return _ambiguous("当前对话关联了多个任务，请说明要继续哪一个。")
    return {"intent": "task", "task_id": str(tasks[0]["id"]) if len(tasks) == 1 else None, "reason": "本地安全回退"}


def _task_words_are_new(content: str) -> bool:
    return any(token in content for token in ("新任务", "另一个任务", "新建"))


def _decision_json(text: str) -> dict[str, object] | None:
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
        if char == "{":
            try:
                value, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None
