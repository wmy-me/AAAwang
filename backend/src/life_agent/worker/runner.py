"""Independent database-backed worker for the safe diagnostic run runner."""

import argparse
import asyncio
import logging
import os
import re
import socket
import threading
import time
import uuid
from dataclasses import replace

from life_agent.agents.coordinator import (
    decide_capabilities,
    validate_discovered_capabilities,
)
from life_agent.agents.coordinator.service import classify_conversation_turn
from life_agent.agents.discovery import build_shopping_prompt
from life_agent.core.budget import BudgetExceededError, RunBudget
from life_agent.core.config import get_settings
from life_agent.core.llm import LLMRequestError, ToolLoopError, run_tool_loop
from life_agent.core.llm.deepseek import call_deepseek
from life_agent.db.session import get_session_factory
from life_agent.modules.capabilities import get_capability
from life_agent.modules.chat.context import ContextBuilder
from life_agent.modules.chat.service import (
    apply_conversation_route,
    conversation_route_inputs,
)
from life_agent.modules.forms.service import persist_model_proposal
from life_agent.modules.memory import MemoryUnavailableError, get_memory_service
from life_agent.modules.runs.service import (
    cancel_claim,
    claim_run,
    complete_claim,
    fail_claim,
    fail_exhausted_runs,
    is_cancel_requested,
    persist_budget_reservation,
    renew_claim,
)

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
            budget = RunBudget.from_snapshot(claim.budget)

            def persist_reservation(snapshot: dict[str, object]) -> None:
                with get_session_factory()() as reservation_db:
                    if not persist_budget_reservation(reservation_db, claim, snapshot):
                        raise BudgetExceededError("lease_lost")

            budget.on_reserve = persist_reservation
            context = ContextBuilder(
                max_messages=settings.conversation_context_max_messages,
                max_characters=settings.conversation_context_max_characters,
            ).build(
                db, claim.owner_id, claim.conversation_id,
                before_message_id=claim.input_message_id,
            )
            # The current user message is supplied separately to each consumer,
            # so it must not be duplicated in the historical view.
            claim = replace(claim, conversation_context=context.as_prompt())
            if is_cancel_requested(db, claim):
                budget.stop("cancelled")
                return cancel_claim(db, claim, budget.snapshot())
            if claim.execution_type == "conversation_route":
                tasks = conversation_route_inputs(db, claim.owner_id, claim.conversation_id)
                classification = classify_conversation_turn(
                    settings,
                    claim.input_message or claim.goal,
                    [{"role": item.role, "content": item.content} for item in context.messages],
                    tasks,
                    budget,
                )
                with get_session_factory()() as route_db:
                    if is_cancel_requested(route_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(route_db, claim, budget.snapshot())
                    claim = apply_conversation_route(route_db, claim, classification, budget.snapshot())
            if claim.execution_type == "direct_answer" and (claim.decision or {}).get("kind") == "memory":
                with get_session_factory()() as memory_db:
                    if is_cancel_requested(memory_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(memory_db, claim, budget.snapshot())
                    try:
                        result = _run_memory_action_with_lease(settings, claim, budget)
                    except MemoryUnavailableError:
                        result = "记忆服务暂不可用，普通对话不受影响；这次记住、修改或删除没有完成。"
                    if is_cancel_requested(memory_db, claim):
                        budget.stop("cancelled")
                        return cancel_claim(memory_db, claim, budget.snapshot())
                    return complete_claim(
                        memory_db, claim,
                        shopping_result={"answer": result, "source": {"service_id": None, "tool": "user_preference_memory", "simulated": False}, "execution_version": "031-v1", "decision_type": "memory", "delegated": False, "mcp_call_count": 0},
                        budget=budget.snapshot(), decision=claim.decision,
                        execution_type=claim.execution_type, capability_ids=claim.capability_ids,
                    )
            if claim.execution_type == "direct_answer":
                try:
                    preferences = get_memory_service().relevant(claim.owner_id, claim.input_message or claim.goal)
                except MemoryUnavailableError:
                    preferences = []
                if preferences:
                    claim = replace(claim, preference_context="；".join(f"{item.metadata.get('memory_key', '偏好')}：{item.content}" for item in preferences))
            _validate_claim_capabilities(claim)
            if claim.execution_type == "capability_decision":
                decision = decide_capabilities(settings, claim, budget)
                if decision["kind"] == "clarification":
                    clarification = str(
                        decision.get("clarification") or "请补充必要信息后再试。"
                    )[:12_000]
                    with get_session_factory()() as result_db:
                        if claim.task_id is not None:
                            persist_model_proposal(
                                result_db, claim.task_id, claim.revision, decision.get("form_schema")
                            )
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
                    else "weather"
                    if selected == ("weather_forecast",)
                    else "map_places"
                    if selected == ("map_place_search",)
                    else "web_search"
                    if selected == ("web_search",)
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
                validate_discovered_capabilities(settings, claim, budget)
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
                    if claim.task_id is not None:
                        persist_model_proposal(
                            result_db, claim.task_id, claim.revision, decision.get("form_schema")
                        )
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
                    persist_model_proposal(
                        result_db, claim.task_id, claim.revision,
                        (claim.decision or {}).get("form_schema"),
                    )
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
                from life_agent.agents.procurement.service import build_validated_plan

                source = dict(result.source)
                source.update(
                    {
                        "delegations": 1 if result.delegated else 0,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "stop_reason": "completed",
                        "budget": budget.snapshot(),
                    }
                )
                artifacts, validated_answer = build_validated_plan(source, claim.conditions)
                answer = validated_answer or result.answer
                with get_session_factory()() as result_db:
                    persist_model_proposal(
                        result_db, claim.task_id, claim.revision,
                        (claim.decision or {}).get("form_schema"),
                    )
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
                    persist_model_proposal(
                        result_db, claim.task_id, claim.revision,
                        (claim.decision or {}).get("form_schema"),
                    )
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
            if claim.execution_type == "weather":
                result = _run_weather_with_lease(settings, claim, budget)
                with get_session_factory()() as result_db:
                    persist_model_proposal(
                        result_db,
                        claim.task_id,
                        claim.revision,
                        (claim.decision or {}).get("form_schema"),
                    )
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
            if claim.execution_type == "web_search":
                result = _run_web_search_with_lease(settings, claim, budget)
                with get_session_factory()() as result_db:
                    persist_model_proposal(
                        result_db,
                        claim.task_id,
                        claim.revision,
                        (claim.decision or {}).get("form_schema"),
                    )
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
                    persist_model_proposal(
                        result_db, claim.task_id, claim.revision,
                        (claim.decision or {}).get("form_schema"),
                    )
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
                budget.stop(_termination_reason(exc))
                return fail_claim(fail_db, claim, error_summary, budget.snapshot())


def _termination_reason(exc: Exception) -> str:
    """Map worker failures to a bounded, user-readable termination reason."""
    if isinstance(exc, BudgetExceededError):
        return str(exc)
    if isinstance(exc, TimeoutError):
        return "timeout"
    if "租约丢失" in str(exc):
        return "lease_lost"
    if "超过总执行时限" in str(exc):
        return "timeout"
    return "failed"


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


def _run_direct_answer_with_lease(settings, claim, budget) -> str:
    prompt = (
        f"用户请求：{claim.input_message or claim.goal}\n"
        f"已确认条件：{_bounded_json(claim.conditions)}\n"
        f"近期对话（可能已裁剪）：{claim.conversation_context or '（无）'}\n"
        f"与本轮相关的用户明确长期偏好（仅供参考，当前用户要求优先）：{claim.preference_context or '（无）'}\n"
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


def _run_memory_action_with_lease(settings, claim, budget) -> str:
    """Keep the normal worker lease alive around synchronous Mem0 SDK work."""
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

    heartbeat = threading.Thread(target=renew, name="memory-lease-renewal", daemon=True)
    heartbeat.start()
    try:
        result = get_memory_service().apply(
            claim.owner_id, claim.input_message_id, claim.decision or {}, budget
        )
        if lease_lost.is_set():
            raise ToolLoopError("记忆操作租约丢失，结果不会提交；请创建新的 run 重试。")
        return result
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


def _map_request(
    goal: str, input_message: str | None, context: str = ""
) -> tuple[str, str | None]:
    text = f"{input_message or goal} {context}".strip()
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

    query, city = _map_request(claim.goal, claim.input_message, claim.conversation_context)
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


_WEATHER_CITY_PATTERNS = (
    re.compile(
        r"(?:请|帮我)?\s*(?:查询|查找|搜索|查|看看|看一下|了解|告诉我)\s*"
        r"([一-鿿]{2,12}?)(?:市)?\s*(?:的)?\s*(?:天气|气温|温度|预报|会下雨)"
    ),
    re.compile(
        r"(?:天气|气温|温度|预报)\s*(?:查询|查|看)?\s*"
        r"([一-鿿]{2,12}?)(?:市)?"
    ),
    re.compile(r"([一-鿿]{2,12}?)(?:市)?\s*(?:的)?\s*(?:天气|气温|温度|预报|会下雨)"),
)


def _weather_city(goal: str, input_message: str | None) -> str | None:
    text = (input_message or goal).strip()
    for pattern in _WEATHER_CITY_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _run_weather_with_lease(settings, claim, budget=None):
    from life_agent.tools.maps import query_weather

    city = _weather_city(claim.goal, claim.input_message)
    if not city:
        return {
            "answer": "请先告诉我需要查询天气的城市。",
            "source": {"service_id": "map", "tool": None, "simulated": False},
            "execution_version": "023-v1",
            "decision_type": "clarification",
            "delegated": False,
            "mcp_call_count": 0,
        }
    if budget is not None:
        budget.reserve("mcp")
    result = asyncio.run(
        asyncio.wait_for(
            query_weather(settings, city),
            timeout=settings.map_mcp_timeout_seconds,
        )
    )
    forecasts = result["forecasts"]
    return {
        "answer": f"已查询 {result['city']} 的天气，返回 {len(forecasts)} 天预报。",
        "source": result["source"],
        "execution_version": "023-v1",
        "decision_type": "direct_answer",
        "delegated": False,
        "mcp_call_count": 1,
        "weather": result,
    }


def _web_search_query(goal: str, input_message: str | None) -> str:
    text = (input_message or goal).strip()
    text = re.sub(
        r"^(?:请|帮我|麻烦|想了解|我想了解|搜索|查询|网上查|网页搜索)\s*", "", text
    )
    return text[:500] or goal[:500]


def _run_web_search_with_lease(settings, claim, budget=None):
    from life_agent.tools.search import search_web

    query = _web_search_query(claim.goal, claim.input_message)
    if budget is not None:
        budget.reserve("mcp")
    result = asyncio.run(
        asyncio.wait_for(
            search_web(settings, query),
            timeout=settings.tavily_mcp_timeout_seconds,
        )
    )
    return {
        "answer": (
            f"已搜索公开网页，查询“{query}”，返回 {len(result['results'])} 条来源。"
            "网页摘要仅作为外部资料，不代表已验证的商品报价、库存或事实。"
        ),
        "source": result["source"],
        "execution_version": "027-v1",
        "decision_type": "direct_answer",
        "delegated": False,
        "mcp_call_count": 1,
        "web_search": result,
    }


def _run_shopping_agent_with_lease(settings, claim, *, force_discovery: bool = False, budget=None):
    from life_agent.agents.discovery.service import run_product_discovery

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
                    run_product_discovery(
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
                build_shopping_prompt(claim.goal, claim.conditions),
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
    from life_agent.tools.maps import MapPlaceSearchError, WeatherQueryError

    if isinstance(error, (MapPlaceSearchError, WeatherQueryError)):
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
    if claim.execution_type == "weather" and claim.capability_ids not in (
        (),
        ("weather_forecast",),
    ):
        raise ToolLoopError("天气 Run 的能力快照无效。")
    if claim.execution_type == "web_search" and claim.capability_ids not in (
        (),
        ("web_search",),
    ):
        raise ToolLoopError("网页搜索 Run 的能力快照无效。")
    if claim.execution_type == "capability_router":
        allowed = {
            "map_place_search",
            "shopping_product_discovery",
            "weather_forecast",
            "web_search",
        }
        if len(claim.capability_ids) < 2 or not set(claim.capability_ids) <= allowed:
            raise ToolLoopError("组合 Run 缺少能力快照。")


def _run_capability_router_with_lease(settings, claim, budget=None):
    """Run the selected read-only capabilities once, inside one durable Run."""
    selected = set(claim.capability_ids)
    map_result = None
    shopping_result = None
    weather_result = None
    web_search_result = None
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
        from life_agent.agents.procurement.service import build_validated_plan

        source = dict(shopping_agent.source)
        source.update(
            {
                "delegations": 1 if shopping_agent.delegated else 0,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "stop_reason": "completed",
                "budget": budget.snapshot() if budget is not None else None,
            }
        )
        artifacts, validated_answer = build_validated_plan(source, claim.conditions)
        shopping_result = {
            "answer": validated_answer or shopping_agent.answer,
            "source": source,
            "execution_version": "019-v1",
            "decision_type": shopping_agent.decision_type,
            "delegated": shopping_agent.delegated,
            "mcp_call_count": shopping_agent.mcp_call_count,
        }
    if "weather_forecast" in selected:
        weather_result = _run_weather_with_lease(settings, claim, budget)
    if "web_search" in selected:
        web_search_result = _run_web_search_with_lease(settings, claim, budget)
    primary = shopping_result or map_result or weather_result or web_search_result
    if primary is None:
        return None, artifacts
    if weather_result is not None and primary is not weather_result:
        primary["answer"] = f"{primary['answer']}\n{weather_result['answer']}"
        primary["weather"] = weather_result.get("weather")
        primary["mcp_call_count"] = int(primary.get("mcp_call_count", 0)) + int(
            weather_result.get("mcp_call_count", 0)
        )
    if map_result is not None and primary is not map_result:
        primary["answer"] = f"{map_result['answer']}\n{primary['answer']}"
        primary["map_source"] = map_result["source"]
        primary["places"] = map_result["places"]
        primary["query"] = map_result["query"]
        primary["city"] = map_result["city"]
        primary["observed_at"] = map_result["observed_at"]
        primary["mcp_call_count"] = int(primary.get("mcp_call_count", 0)) + int(
            map_result["mcp_call_count"]
        )
    if web_search_result is not None and primary is not web_search_result:
        primary["answer"] = f"{primary['answer']}\n{web_search_result['answer']}"
        primary["web_search"] = web_search_result["web_search"]
        primary["web_source"] = web_search_result["source"]
        primary["mcp_call_count"] = int(primary.get("mcp_call_count", 0)) + int(
            web_search_result["mcp_call_count"]
        )
    return primary, artifacts


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
