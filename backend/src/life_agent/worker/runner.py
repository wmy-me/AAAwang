"""Independent database-backed worker for the safe diagnostic run runner."""

import argparse
import asyncio
import json
import logging
import os
import re
import socket
import threading
import time
import uuid
from dataclasses import replace

from life_agent.core.budget import BudgetExceededError, RunBudget
from life_agent.core.config import get_settings
from life_agent.core.llm import LLMRequestError, ToolLoopError, run_tool_loop
from life_agent.core.llm.deepseek import call_deepseek
from life_agent.db.session import get_session_factory
from life_agent.modules.capabilities import (
    get_capability,
    has_location_scope,
    visible_capabilities,
)
from life_agent.modules.runs.service import (
    cancel_claim,
    claim_run,
    complete_claim,
    fail_claim,
    fail_exhausted_runs,
    is_cancel_requested,
    renew_claim,
)
from life_agent.tools.mcp import McpClient, McpClientError

logger = logging.getLogger(__name__)


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def run_once(worker_id: str) -> bool:
    settings = get_settings()
    with get_session_factory()() as db:
        fail_exhausted_runs(db, settings.run_worker_max_attempts)
        claim = claim_run(
            db,
            worker_id,
            settings.run_worker_lease_seconds,
            settings.run_worker_max_attempts,
        )
        if claim is None:
            return False
        try:
            budget = RunBudget()
            if is_cancel_requested(db, claim):
                budget.stop("cancelled")
                return cancel_claim(db, claim, budget.snapshot())
            _validate_claim_capabilities(claim)
            if claim.execution_type == "capability_decision":
                decision = _run_capability_decision(settings, claim, budget)
                if decision["kind"] == "clarification":
                    clarification = str(
                        decision.get("clarification") or "请补充必要信息后再试。"
                    )[:12_000]
                    with get_session_factory()() as result_db:
                        return complete_claim(
                            result_db,
                            claim,
                            shopping_result={
                                "answer": clarification,
                                "source": {"service_id": None, "tool": None, "simulated": False},
                                "execution_version": "020-v1",
                                "decision_type": "clarification",
                                "delegated": False,
                                "mcp_call_count": 0,
                            },
                            budget=budget.snapshot(),
                            decision=decision,
                            execution_type="direct_answer",
                            capability_ids=(),
                        )
                selected = tuple(decision.get("capability_ids", ()))
                execution_type = (
                    "capability_router"
                    if len(selected) > 1
                    else "map_places"
                    if selected == ("map_place_search",)
                    else "shopping_agent"
                    if selected == ("shopping_product_discovery",)
                    else "direct_answer"
                )
                claim = replace(
                    claim,
                    execution_type=execution_type,
                    capability_ids=selected,
                    decision=decision,
                )
                _validate_discovered_capabilities(settings, claim, budget)
            if claim.execution_type == "direct_answer":
                decision = claim.decision or {
                    "kind": "direct",
                    "capability_ids": [],
                }
                if decision.get("kind") == "clarification":
                    result = str(
                        decision.get("clarification")
                        or "请补充必要信息后再试。"
                    )[:12_000]
                else:
                    result = _run_direct_answer_with_lease(settings, claim, budget)
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(result_db, claim, budget.snapshot())
                    return complete_claim(
                        result_db,
                        claim,
                        shopping_result={
                            "answer": result,
                            "source": {"service_id": None, "tool": None, "simulated": False},
                            "execution_version": "020-v1",
                            "decision_type": "direct_answer",
                            "delegated": False,
                            "mcp_call_count": 0,
                        },
                        budget=budget.snapshot(),
                        decision=decision,
                        execution_type=claim.execution_type,
                        capability_ids=claim.capability_ids,
                    )
            if claim.execution_type == "shopping_research":
                result = _run_shopping_with_lease(settings, claim, budget)
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(result_db, claim, budget.snapshot())
                    return complete_claim(
                        result_db,
                        claim,
                        shopping_result={
                            "answer": result.answer[:12_000],
                            "source": {
                                "service_id": result.service_id,
                                "tool": result.called_tool,
                                "simulated": True,
                                "tool_result": _bounded_json(result.tool_result),
                                "model_requests": result.model_requests,
                                "tool_calls": result.tool_calls,
                            },
                            "execution_version": "010-v1",
                            "budget": budget.snapshot(),
                        },
                        budget=budget.snapshot(),
                        decision=_decision_for_completion(claim),
                        execution_type=claim.execution_type,
                        capability_ids=claim.capability_ids,
                    )
            if claim.execution_type == "shopping_agent":
                started = time.monotonic()
                result = _run_shopping_agent_with_lease(settings, claim, budget=budget)
                from life_agent.modules.shopping_plans.service import (
                    build_artifacts,
                    validated_plan_answer,
                )

                source = dict(result.source)
                source.update(
                    {
                        "delegations": 1 if result.delegated else 0,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "stop_reason": "completed",
                        "budget": budget.snapshot(),
                    }
                )
                artifacts = build_artifacts(source, claim.conditions)
                answer = validated_plan_answer(artifacts) or result.answer
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(result_db, claim, budget.snapshot())
                    return complete_claim(
                        result_db,
                        claim,
                        shopping_result={
                            "answer": answer[:12_000],
                            "source": source,
                            "execution_version": "015-v1",
                            "decision_type": result.decision_type,
                            "delegated": result.delegated,
                            "mcp_call_count": result.mcp_call_count,
                        },
                        shopping_artifacts=artifacts,
                        budget=budget.snapshot(),
                        decision=_decision_for_completion(claim),
                        execution_type=claim.execution_type,
                        capability_ids=claim.capability_ids,
                    )
            if claim.execution_type == "map_places":
                result = _run_map_places_with_lease(settings, claim, budget)
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(result_db, claim, budget.snapshot())
                    return complete_claim(
                        result_db,
                        claim,
                        shopping_result=result,
                        budget=budget.snapshot(),
                        decision=_decision_for_completion(claim),
                        execution_type=claim.execution_type,
                        capability_ids=claim.capability_ids,
                    )
            if claim.execution_type == "capability_router":
                result, artifacts = _run_capability_router_with_lease(settings, claim, budget)
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(result_db, claim, budget.snapshot())
                    return complete_claim(
                        result_db,
                        claim,
                        shopping_result=result,
                        shopping_artifacts=artifacts,
                        budget=budget.snapshot(),
                        decision=_decision_for_completion(claim),
                        execution_type=claim.execution_type,
                        capability_ids=claim.capability_ids,
                    )
            return complete_claim(
                db,
                claim,
                diagnostic={
                    "runner": "diagnostic",
                    "message": "尚未运行 Agent 规划。",
                    "task_id": str(claim.task_id),
                    "task_revision_id": str(claim.task_revision_id),
                    "revision": claim.revision,
                },
                budget=budget.snapshot(),
                decision={"kind": "diagnostic", "capability_ids": []},
                execution_type=claim.execution_type,
                capability_ids=claim.capability_ids,
            )
        except Exception as exc:  # noqa: BLE001
            error_summary = _safe_error(exc)
            logger.error(
                "run execution failed: run_id=%s execution_type=%s error=%s",
                claim.run_id,
                claim.execution_type,
                error_summary,
            )
            with get_session_factory()() as fail_db:
                if isinstance(exc, BudgetExceededError):
                    reason = str(exc)
                elif isinstance(exc, TimeoutError):
                    reason = "timeout"
                elif "租约丢失" in str(exc):
                    reason = "lease_lost"
                else:
                    reason = "failed"
                budget.stop(reason)
                return fail_claim(fail_db, claim, error_summary, budget.snapshot())


def _capability_decision(claim) -> dict[str, object]:
    return {
        "kind": "capabilities",
        "capability_ids": list(claim.capability_ids),
    }


def _decision_for_completion(claim) -> dict[str, object]:
    """Keep the model's validated decision when the run came from a decision step."""
    if claim.decision and claim.decision.get("kind") == "capabilities":
        return dict(claim.decision)
    return _capability_decision(claim)


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


def _run_capability_decision(settings, claim, budget) -> dict[str, object]:
    """Ask the model for a bounded decision, then validate it server-side."""
    enabled, discovered = _discover_capability_tools(settings, budget)
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
        '"capability_ids":[],"clarification":null,"reason":"简短原因"}\n'
        "capability_ids 只能从下列后端授权集合中选择，不能创建新 ID、URL、服务或工具：\n"
        f"{capability_lines}\n"
        f"用户消息：{claim.input_message or claim.goal}\n"
        f"当前任务条件：{_bounded_json(claim.conditions)}\n"
        "判断规则：\n"
        "1. 问候、询问你能做什么、闲聊或解释概念：kind=direct，capability_ids=[]，不要调用工具。\n"
        "2. 用户本轮明确要查找地点/店铺/附近/路线，但没有城市或位置范围：kind=clarification。\n"
        "3. 城市名（如上海、北京）本身已是有效位置范围，不要要求区或街道；"
        "“查询上海附近的书店”应选择 map_place_search。\n"
        "4. 用户本轮要求购买、查找或推荐具体商品（如“买彩色铅笔作为奖品”"
        "“给25人买彩色铅笔”）时，选择 shopping_product_discovery。\n"
        "5. 只有任务条件或历史目标提到预算、人数，而本轮没有商品或地点请求时，"
        "才不要选择能力。\n"
        "只读查询不因缺预算而阻断；无法判断时选择 direct 或 clarification，不要猜测能力。"
    )
    response = asyncio.run(call_deepseek(settings, prompt, budget=budget))
    value = _decision_json(response.text)
    if value is None:
        raise ToolLoopError("能力决策不是有效 JSON，已拒绝执行。")
    kind = value.get("kind")
    if kind not in {"direct", "clarification", "capabilities"}:
        raise ToolLoopError("能力决策类型未注册，已拒绝执行。")
    selected = value.get("capability_ids", [])
    if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
        raise ToolLoopError("能力决策的 capability_ids 无效。")
    visible_ids = {item.capability_id for item in visible}
    if any(item not in visible_ids for item in selected) or len(set(selected)) != len(selected):
        raise ToolLoopError("模型选择了当前不可见或重复的能力。")
    if kind == "capabilities" and not selected:
        raise ToolLoopError("capabilities 决策必须选择至少一项能力。")
    if kind != "capabilities" and selected:
        # Models sometimes label a tool-using reply "direct"; capability_ids are
        # validated against the visible set, so treat them as authoritative.
        kind = "capabilities"
    if "map_place_search" in selected and not has_location_scope(claim.input_message or claim.goal):
        return {
            "kind": "clarification",
            "capability_ids": [],
            "clarification": "请先告诉我需要查询的城市或位置范围。",
            "reason": "后端校验发现地图查询缺少位置范围",
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
        "decision_source": "deepseek_structured_worker",
    }


def _discover_capability_tools(settings, budget: RunBudget | None = None):
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
                logger.warning("MCP capability discovery unavailable: service=%s", service_id)
                continue
            enabled.add(service_id)
            discovered[service_id] = {
                tool.name: dict(tool.tool.input_schema or {}) for tool in tools
            }
        return enabled, discovered

    return asyncio.run(discover())


def _validate_discovered_capabilities(settings, claim, budget: RunBudget | None = None) -> None:
    """Re-discover selected services immediately before capability execution."""
    if not claim.capability_ids:
        return
    _, discovered = _discover_capability_tools(settings, budget)
    visible = visible_capabilities(
        task_domain="shopping",
        enabled_services=set(discovered),
        discovered_tools=discovered,
    )
    visible_ids = {item.capability_id for item in visible}
    if any(item not in visible_ids for item in claim.capability_ids):
        raise ToolLoopError("执行前 MCP 工具发现结果已变化，能力不可用。")


def _shopping_prompt(goal: str, conditions: dict[str, object]) -> str:
    known = ", ".join(f"{key}={value}" for key, value in conditions.items()) or "无"
    return (
        f"购物目标：{goal}\n已知条件：{known}\n"
        "只查询并回答模拟商品候选。未提供的预算、物品、数量必须明确写为未知，不能猜测。"
    )


def _run_direct_answer_with_lease(settings, claim, budget) -> str:
    prompt = (
        f"用户请求：{claim.input_message or claim.goal}\n"
        f"已确认条件：{_bounded_json(claim.conditions)}\n"
        "请直接回答，不要调用任何工具；未知信息要明确说明。"
    )
    stop = threading.Event()
    lease_lost = threading.Event()

    def renew() -> None:
        interval = max(0.5, settings.run_worker_lease_seconds / 3)
        while not stop.wait(interval):
            try:
                with get_session_factory()() as lease_db:
                    if not renew_claim(lease_db, claim, settings.run_worker_lease_seconds):
                        lease_lost.set()
                        return
            except Exception:
                logger.exception("run lease renewal failed for %s", claim.run_id)
                lease_lost.set()
                return

    heartbeat = threading.Thread(target=renew, name="run-lease-renewal", daemon=True)
    heartbeat.start()
    try:
        result = asyncio.run(
            asyncio.wait_for(
                call_deepseek(settings, prompt, budget=budget),
                timeout=settings.shopping_agent_total_timeout_seconds,
            )
        )
        if lease_lost.is_set():
            raise ToolLoopError("直答执行租约丢失，结果不会提交；请创建新的 run 重试。")
        return result.text[:12_000]
    finally:
        stop.set()
        heartbeat.join(timeout=2)


_MAP_CITY_PATTERNS = (
    re.compile(
        r"(?:在|到|位于)\s*([^，。；;,\s]{2,20}?)(?=\s*(?:找|查|搜|看|的|附近|周边|有|$|[，。；;,]))"
    ),
    re.compile(
        r"^(?:帮我|请|麻烦)?\s*(?:查询|查找|搜索)(?:一下)?\s*"
        r"([一-鿿]{2,8}?)(?=(?:的)?(?:附近|周边|礼品|超市|商场|门店|店铺|地点|位置|店))"
    ),
    re.compile(
        r"(?:看看|看一下|查查|找找|查询|查找|搜索|找)\s*"
        r"([一-鿿]{2,8}?)(?:市|区|县)?(?:附近|周边)"
    ),
    re.compile(r"^([一-鿿]{2,8}?)(?:市|区|县)?(?:附近|周边)"),
)

_CLAUSE_SPLIT = re.compile(r"[，。；;,]|(?:并|同时|以及|然后|再)")
_MAP_CLAUSE_HINT = re.compile(r"(附近|周边|地点|位置|地图|礼品店|哪里买)")


def _clauses(text: str) -> list[str]:
    return [clause.strip() for clause in _CLAUSE_SPLIT.split(text) if clause.strip()]


def _map_request(goal: str, input_message: str | None) -> tuple[str, str | None]:
    text = (input_message or goal).strip()
    city = next(
        (match.group(1) for pattern in _MAP_CITY_PATTERNS if (match := pattern.search(text))),
        None,
    )
    clauses = _clauses(text)
    target = next(
        (
            clause
            for clause in clauses
            if _MAP_CLAUSE_HINT.search(clause) and (city is None or city in clause)
        ),
        None,
    )
    if target is None:
        target = next(
            (clause for clause in clauses if _MAP_CLAUSE_HINT.search(clause)),
            text,
        )
    query = target.replace(city, " ", 1) if city else target
    query = re.sub(
        r"(?:帮我|请|麻烦|查询|查找|搜索|搜一下|找一下|看看|看一下|找|在|到|位于|"
        r"附近的|附近|周边的|周边|的|地点|位置|哪里买|有卖)",
        " ",
        query,
    )
    query = " ".join(query.split())[:120]
    return query or text[:120], city


def _run_map_places_with_lease(settings, claim, budget=None):
    from life_agent.tools.maps import search_places

    query, city = _map_request(claim.goal, claim.input_message)
    if not city:
        return {
            "answer": "请先告诉我需要查询的城市或位置范围。",
            "source": {"service_id": "map", "tool": None, "simulated": False},
            "execution_version": "018-v1",
            "decision_type": "clarification",
            "delegated": False,
            "mcp_call_count": 0,
            "places": [], "query": query, "city": "",
        }
    if budget is not None:
        budget.reserve("mcp")
    result = asyncio.run(
        asyncio.wait_for(
            search_places(settings, query, city=city),
            timeout=settings.map_mcp_timeout_seconds,
        )
    )
    return {
        "answer": f"已查询 {city} 的“{query}”，找到 {len(result['places'])} 个地点。",
        "source": result["source"],
        "execution_version": "018-v1",
        "decision_type": "direct_answer",
        "delegated": False,
        "mcp_call_count": 1,
        "places": result["places"], "query": query, "city": city,
        "observed_at": result["observed_at"],
    }


def _run_shopping_agent_with_lease(settings, claim, *, force_discovery: bool = False, budget=None):
    from life_agent.agents.shopping import run_shopping_agent

    stop = threading.Event()
    lease_lost = threading.Event()

    def renew() -> None:
        interval = max(0.5, settings.run_worker_lease_seconds / 3)
        while not stop.wait(interval):
            try:
                with get_session_factory()() as lease_db:
                    if not renew_claim(lease_db, claim, settings.run_worker_lease_seconds):
                        lease_lost.set()
                        return
            except Exception:
                logger.exception("run lease renewal failed for %s", claim.run_id)
                lease_lost.set()
                return

    heartbeat = threading.Thread(target=renew, name="run-lease-renewal", daemon=True)
    heartbeat.start()
    try:
        goal = claim.goal
        if claim.input_message:
            goal = f"{goal}\n本轮用户消息：{claim.input_message}"
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    run_shopping_agent(
                        settings,
                        goal,
                        claim.conditions,
                        force_discovery=force_discovery,
                        budget=budget,
                    ),
                    timeout=settings.shopping_agent_total_timeout_seconds,
                )
            )
        except TimeoutError as exc:
            raise ToolLoopError(
                "购物Agent超过总执行时限，结果不会提交；请创建新的 run 重试。"
            ) from exc
        if lease_lost.is_set():
            raise ToolLoopError("购物Agent执行租约丢失，结果不会提交；请创建新的 run 重试。")
        return result
    finally:
        stop.set()
        heartbeat.join(timeout=2)


def _run_shopping_with_lease(settings, claim, budget=None):
    stop = threading.Event()
    lease_lost = threading.Event()

    def renew() -> None:
        interval = max(0.5, settings.run_worker_lease_seconds / 3)
        while not stop.wait(interval):
            try:
                with get_session_factory()() as lease_db:
                    if not renew_claim(lease_db, claim, settings.run_worker_lease_seconds):
                        lease_lost.set()
                        return
            except Exception:
                logger.exception("run lease renewal failed for %s", claim.run_id)
                lease_lost.set()
                return

    heartbeat = threading.Thread(target=renew, name="run-lease-renewal", daemon=True)
    heartbeat.start()
    try:
        result = asyncio.run(
            run_tool_loop(
                settings,
                _shopping_prompt(claim.goal, claim.conditions),
                service_id="shopping",
                allowed_tool_names=("search_products",),
                total_timeout_seconds=90.0,
                budget=budget,
            )
        )
        if lease_lost.is_set():
            raise ToolLoopError("购物执行租约丢失，结果不会提交；请创建新的 run 重试。")
        return result
    finally:
        stop.set()
        heartbeat.join(timeout=2)


def _bounded_json(value: object) -> object:
    if value is None:
        return None
    text = str(value)
    return text[:12_000]


def _safe_error(error: Exception) -> str:
    from life_agent.tools.maps import MapPlaceSearchError

    if isinstance(error, MapPlaceSearchError):
        return f"map_{error.code}"
    if isinstance(error, (ToolLoopError, LLMRequestError)):
        return str(error)[:500]
    return "shopping execution failed; external call history may be uncertain"


def _validate_claim_capabilities(claim) -> None:
    """Re-check the trusted capability snapshot immediately before execution."""
    for capability_id in claim.capability_ids:
        capability = get_capability(capability_id)
        if capability.task_domain != "shopping" or not capability.read_only:
            raise ToolLoopError("能力不允许在当前购物任务中执行。")
    if claim.execution_type == "map_places" and claim.capability_ids not in (
        (),
        ("map_place_search",),
    ):
        raise ToolLoopError("地点 Run 的能力快照无效。")
    if claim.execution_type == "shopping_agent" and claim.capability_ids not in (
        (),
        ("shopping_product_discovery",),
    ):
        raise ToolLoopError("商品 Run 的能力快照无效。")
    if claim.execution_type == "capability_router" and claim.capability_ids not in (
        ("map_place_search", "shopping_product_discovery"),
        ("shopping_product_discovery", "map_place_search"),
    ):
        raise ToolLoopError("组合 Run 缺少能力快照。")


def _run_capability_router_with_lease(settings, claim, budget=None):
    """Run the selected read-only capabilities once, inside one durable Run."""
    selected = set(claim.capability_ids)
    map_result = None
    shopping_result = None
    artifacts = None
    if "map_place_search" in selected:
        map_result = _run_map_places_with_lease(settings, claim, budget)
    if "shopping_product_discovery" in selected:
        started = time.monotonic()
        shopping_text = claim.input_message or claim.goal
        shopping_goal = "，".join(
            clause
            for clause in _clauses(shopping_text)
            if not _MAP_CLAUSE_HINT.search(clause)
        )
        shopping_claim = replace(
            claim,
            goal=shopping_goal or shopping_text,
            input_message=None,
        )
        shopping_agent = _run_shopping_agent_with_lease(
            settings, shopping_claim, force_discovery=True, budget=budget
        )
        from life_agent.modules.shopping_plans.service import (
            build_artifacts,
            validated_plan_answer,
        )

        source = dict(shopping_agent.source)
        source.update(
            {
                "delegations": 1 if shopping_agent.delegated else 0,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "stop_reason": "completed",
                "budget": budget.snapshot() if budget is not None else None,
            }
        )
        artifacts = build_artifacts(source, claim.conditions)
        shopping_result = {
            "answer": validated_plan_answer(artifacts) or shopping_agent.answer,
            "source": source,
            "execution_version": "019-v1",
            "decision_type": shopping_agent.decision_type,
            "delegated": shopping_agent.delegated,
            "mcp_call_count": shopping_agent.mcp_call_count,
        }
    if map_result is not None and shopping_result is not None:
        shopping_result["answer"] = f"{map_result['answer']}\n{shopping_result['answer']}"
        shopping_result["map_source"] = map_result["source"]
        shopping_result["places"] = map_result["places"]
        shopping_result["query"] = map_result["query"]
        shopping_result["city"] = map_result["city"]
        shopping_result["observed_at"] = map_result["observed_at"]
        shopping_result["mcp_call_count"] = int(shopping_result["mcp_call_count"]) + int(
            map_result["mcp_call_count"]
        )
    return shopping_result or map_result, artifacts


def run_forever(worker_id: str) -> None:
    settings = get_settings()
    logger.info("worker started: %s", worker_id)
    while True:
        try:
            if not run_once(worker_id):
                time.sleep(settings.run_worker_poll_seconds)
        except KeyboardInterrupt:
            logger.info("worker stopped: %s", worker_id)
            return
        except Exception:
            logger.exception("worker poll failed")
            time.sleep(settings.run_worker_poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the persistent diagnostic worker")
    parser.add_argument("--worker-id", default=default_worker_id())
    parser.add_argument("--once", action="store_true", help="claim at most one run")
    args = parser.parse_args()
    if args.once:
        run_once(args.worker_id)
    else:
        run_forever(args.worker_id)


if __name__ == "__main__":
    main()