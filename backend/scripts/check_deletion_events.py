"""Verify real PostgreSQL deletion cascades and durable run event invariants."""

import os
import secrets
import uuid

import httpx
from sqlalchemy import delete, select

from life_agent.db.models import Run, RunEvent, User
from life_agent.db.session import get_session_factory


def register_client(base_url: str, username: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=10.0)
    password = f"Local-check-{secrets.token_urlsafe(18)}"
    if client.post("/api/auth/register", json={"username": username, "password": password}).status_code != 201:
        raise RuntimeError("register failed")
    if client.post("/api/auth/login", json={"username": username, "password": password}).status_code != 200:
        raise RuntimeError("login failed")
    return client


def create_cancelled_run(client: httpx.Client, key: str) -> str:
    conversation = client.post("/api/conversations", json={"title": key}).json()
    task = client.post(
        f"/api/conversations/{conversation['id']}/tasks",
        json={
            "domain": "shopping",
            "goal": "Deletion regression",
            "conditions": {"budget": 10, "quantity": 1},
        },
    ).json()
    run = client.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": key},
    ).json()
    if client.post(f"/api/runs/{run['id']}/cancel").json()["status"] != "cancelled":
        raise RuntimeError("cancel failed")
    return run["id"]


def main() -> int:
    base_url = os.environ.get("CHECK_RUNS_BASE_URL", "http://127.0.0.1:18009")
    alice_name = f"delete_009_{secrets.token_hex(6)}"
    bob_name = f"keep_009_{secrets.token_hex(6)}"
    direct_name = f"direct_delete_009_{secrets.token_hex(6)}"
    alice = register_client(base_url, alice_name)
    bob = register_client(base_url, bob_name)
    direct = register_client(base_url, direct_name)
    try:
        alice_run_id = uuid.UUID(create_cancelled_run(alice, "alice-delete"))
        bob_run_id = uuid.UUID(create_cancelled_run(bob, "bob-keep"))
        direct_run_id = uuid.UUID(create_cancelled_run(direct, "direct-delete"))
        with get_session_factory()() as db:
            alice_user = db.scalar(select(User).where(User.username == alice_name))
            if alice_user is None:
                raise RuntimeError("alice user missing")
            db.delete(alice_user)
            db.commit()
            if db.scalar(select(Run).where(Run.id == alice_run_id)) is not None:
                raise RuntimeError("alice run survived user deletion")
            if db.scalar(select(RunEvent).where(RunEvent.run_id == alice_run_id)) is not None:
                raise RuntimeError("alice event survived user deletion")
            if db.scalar(select(Run).where(Run.id == bob_run_id)) is None:
                raise RuntimeError("bob run was deleted across user boundary")
            direct_user = db.scalar(select(User).where(User.username == direct_name))
            if direct_user is None:
                raise RuntimeError("direct-delete user missing")
            db.execute(delete(User).where(User.id == direct_user.id))
            db.commit()
            if db.scalar(select(Run).where(Run.id == direct_run_id)) is not None:
                raise RuntimeError("direct-delete run survived parent DELETE")
            if db.scalar(select(RunEvent).where(RunEvent.run_id == direct_run_id)) is not None:
                raise RuntimeError("direct-delete event survived parent DELETE")
        print("真实 PostgreSQL 删除链: 用户Run与事件清理成功")
        print("真实 PostgreSQL 父表 DELETE: 用户Run与事件级联清理成功")
        print("跨用户隔离: 另一用户Run保留")
        print("状态: 成功")
        return 0
    finally:
        alice.close()
        bob.close()
        direct.close()


if __name__ == "__main__":
    raise SystemExit(main())
