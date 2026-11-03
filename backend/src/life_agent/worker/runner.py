"""Independent database-backed worker for the safe diagnostic run runner."""

import argparse
import asyncio
import logging
import os
import socket
import threading
import time
import uuid

from life_agent.core.config import get_settings
from life_agent.core.llm import ToolLoopError, run_tool_loop
from life_agent.db.session import get_session_factory
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
        except Exception as exc:
            logger.exception("run execution failed for %s", claim.run_id)
            with get_session_factory()() as fail_db:
                return fail_claim(fail_db, claim, _safe_error(exc))


def _shopping_prompt(goal: str, conditions: dict[str, object]) -> str:
    known = ", ".join(f"{key}={value}" for key, value in conditions.items()) or "无"
    return (
        f"购物目标：{goal}\n已知条件：{known}\n"
        "只查询并回答模拟商品候选。未提供的预算、物品、数量必须明确写为未知，不能猜测。"
    )


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
    if isinstance(error, ToolLoopError):
        return str(error)[:500]
    return "shopping execution failed; external call history may be uncertain"


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