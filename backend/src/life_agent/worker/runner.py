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

from life_agent.core.config import get_settings
from life_agent.core.llm import LLMRequestError, ToolLoopError, run_tool_loop
from life_agent.db.session import get_session_factory
from life_agent.modules.capabilities import get_capability
from life_agent.modules.runs.service import (
    cancel_claim,
    claim_run,
    complete_claim,
    fail_claim,
    fail_exhausted_runs,
    is_cancel_requested,
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
            if is_cancel_requested(db, claim):
                return cancel_claim(db, claim)
            _validate_claim_capabilities(claim)
            if claim.execution_type == "shopping_research":
                result = _run_shopping_with_lease(settings, claim)
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        return cancel_claim(result_db, claim)
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
                        },
                    )
            if claim.execution_type == "shopping_agent":
                started = time.monotonic()
                result = _run_shopping_agent_with_lease(settings, claim)
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
                    }
                )
                artifacts = build_artifacts(source, claim.conditions)
                answer = validated_plan_answer(artifacts) or result.answer
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        return cancel_claim(result_db, claim)
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
                    )
            if claim.execution_type == "map_places":
                result = _run_map_places_with_lease(settings, claim)
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        return cancel_claim(result_db, claim)
                    return complete_claim(result_db, claim, shopping_result=result)
            if claim.execution_type == "capability_router":
                result, artifacts = _run_capability_router_with_lease(settings, claim)
                with get_session_factory()() as result_db:
                    if is_cancel_requested(result_db, claim):
                        return cancel_claim(result_db, claim)
                    return complete_claim(
                        result_db,
                        claim,
                        shopping_result=result,
                        shopping_artifacts=artifacts,
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
                return fail_claim(fail_db, claim, error_summary)


def _shopping_prompt(goal: str, conditions: dict[str, object]) -> str:
    known = ", ".join(f"{key}={value}" for key, value in conditions.items()) or "无"
    return (
        f"购物目标：{goal}\n已知条件：{known}\n"
        "只查询并回答模拟商品候选。未提供的预算、物品、数量必须明确写为未知，不能猜测。"
    )


_MAP_CITY_PATTERNS = (
    re.compile(
        r"(?:在|到|位于)\s*([^，。；;,\s]{2,20}?)(?=\s*(?:找|查|搜|看|的|附近|周边|有|$|[，。；;,]))"
    ),
    re.compile(
        r"^(?:帮我|请|麻烦)?\s*(?:查询|查找|搜索)(?:一下)?\s*"
        r"([一-鿿]{2,8}?)(?=(?:的)?(?:附近|周边|礼品|超市|商场|门店|店铺|地点|位置|店))"
    ),
    re.compile(r"^([一-鿿]{2,8}?)(?:市|区|县)?(?:附近|周边)"),
)


def _map_request(goal: str, input_message: str | None) -> tuple[str, str | None]:
    text = (input_message or goal).strip()
    city = next(
        (match.group(1) for pattern in _MAP_CITY_PATTERNS if (match := pattern.search(text))),
        None,
    )
    query = text.replace(city, " ", 1) if city else text
    query = re.sub(
        r"(?:帮我|请|麻烦|查询|查找|搜索|搜一下|找一下|看看|看一下|找|在|到|位于|"
        r"附近的|附近|周边的|周边|的|地点|位置|哪里买|有卖)",
        " ",
        query,
    )
    query = " ".join(query.split())[:120]
    return query or text[:120], city


def _run_map_places_with_lease(settings, claim):
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


def _run_shopping_agent_with_lease(settings, claim):
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
                    run_shopping_agent(settings, goal, claim.conditions),
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


def _run_shopping_with_lease(settings, claim):
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


def _run_capability_router_with_lease(settings, claim):
    """Run the selected read-only capabilities once, inside one durable Run."""
    selected = set(claim.capability_ids)
    map_result = None
    shopping_result = None
    artifacts = None
    if "map_place_search" in selected:
        map_result = _run_map_places_with_lease(settings, claim)
    if "shopping_product_discovery" in selected:
        started = time.monotonic()
        shopping_agent = _run_shopping_agent_with_lease(settings, claim)
        from life_agent.modules.shopping_plans.service import build_artifacts

        source = dict(shopping_agent.source)
        source.update(
            {
                "delegations": 1 if shopping_agent.delegated else 0,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "stop_reason": "completed",
            }
        )
        artifacts = build_artifacts(source, claim.conditions)
        shopping_result = {
            "answer": shopping_agent.answer,
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