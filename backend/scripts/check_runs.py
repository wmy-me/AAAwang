"""Verify persistent runs and independent worker processes on PostgreSQL."""

import os
import secrets
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from life_agent.db.models import Run, User
from life_agent.db.session import get_session_factory
from life_agent.modules.runs.service import claim_run, complete_claim


def main() -> int:
    base_url = os.environ.get("CHECK_RUNS_BASE_URL", "http://127.0.0.1:18007")
    project_root = Path(__file__).resolve().parents[1]
    password = f"Local-check-{secrets.token_urlsafe(18)}"
    username = f"run_007_{secrets.token_hex(6)}"
    created_user_id: uuid.UUID | None = None
    workers: list[subprocess.Popen[str]] = []
    try:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            registered = client.post(
                "/api/auth/register", json={"username": username, "password": password}
            )
            if registered.status_code != 201:
                raise RuntimeError(f"register={registered.status_code}")
            created_user_id = uuid.UUID(registered.json()["id"])
            logged_in = client.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            if logged_in.status_code != 200:
                raise RuntimeError(f"login={logged_in.status_code}")
            conversation = client.post("/api/conversations", json={"title": "runs"})
            conversation_id = conversation.json()["id"]
            task = client.post(
                f"/api/conversations/{conversation_id}/tasks",
                json={
                    "domain": "shopping",
                    "goal": "Read-only run check",
                    "conditions": {"budget": 300, "quantity": 2},
                },
            )
            task_id = task.json()["id"]
            created = client.post(
                f"/api/tasks/{task_id}/runs",
                json={"expected_revision": 1, "idempotency_key": "worker-check"},
            )
            retry = client.post(
                f"/api/tasks/{task_id}/runs",
                json={"expected_revision": 1, "idempotency_key": "worker-check"},
            )
            if created.status_code != 201 or retry.json()["id"] != created.json()["id"]:
                raise RuntimeError("idempotency failed")
            run_id = created.json()["id"]

            command = [sys.executable, "-m", "life_agent.worker.runner", "--once"]
            for worker_id in ("worker-a-007", "worker-b-007"):
                workers.append(
                    subprocess.Popen(
                        [*command, "--worker-id", worker_id],
                        cwd=project_root,
                        env=os.environ.copy(),
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )
            for worker in workers:
                worker.communicate(timeout=20)
            run = client.get(f"/api/runs/{run_id}")
            if run.status_code != 200 or run.json()["status"] != "completed":
                raise RuntimeError(f"worker status={run.status_code} {run.text}")
            if run.json()["diagnostic"]["message"] != "尚未运行 Agent 规划。":
                raise RuntimeError("diagnostic runner message missing")

            second = client.post(
                f"/api/tasks/{task_id}/runs",
                json={"expected_revision": 1, "idempotency_key": "cancel-check"},
            )
            cancelled = client.post(f"/api/runs/{second.json()['id']}/cancel")
            if cancelled.json()["status"] != "cancelled":
                raise RuntimeError("queued cancellation failed")
            crashed = client.post(
                f"/api/tasks/{task_id}/runs",
                json={"expected_revision": 1, "idempotency_key": "lease-check"},
            )
            crashed_id = uuid.UUID(crashed.json()["id"])

        with get_session_factory()() as db:
            stored = db.scalar(select(Run).where(Run.id == uuid.UUID(run_id)))
            if stored is None or stored.attempt != 1:
                raise RuntimeError("run attempt count is not exactly one")
            old_claim = claim_run(db, "crashed-worker-007", 30, 3)
            if old_claim is None:
                raise RuntimeError("crashed worker could not claim run")
            db.execute(
                update(Run)
                .where(Run.id == crashed_id)
                .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
            db.commit()
            recovery_claim = claim_run(db, "recovery-worker-007", 30, 3)
            if recovery_claim is None or complete_claim(db, old_claim, {"late": True}):
                raise RuntimeError("expired worker was not fenced")
            if not complete_claim(db, recovery_claim, {"runner": "diagnostic"}):
                raise RuntimeError("recovery worker could not complete run")
        print("真实 PostgreSQL runs: 创建与幂等成功")
        print("独立 Worker 竞争: 两个进程仅一个领取并完成")
        print("诊断 runner: 未运行 Agent 规划")
        print("排队取消: 成功")
        print("租约过期回收与旧 Worker fencing: 成功")
        print("状态: 成功")
        return 0
    except (httpx.HTTPError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"失败: {exc}")
        return 1
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
        if created_user_id is not None:
            try:
                with get_session_factory()() as db:
                    user = db.scalar(select(User).where(User.id == created_user_id))
                    if user is not None:
                        db.delete(user)
                        db.commit()
            except SQLAlchemyError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
