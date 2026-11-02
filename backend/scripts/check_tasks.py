"""Verify private task revisions and optimistic concurrency on PostgreSQL."""

import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from life_agent.core.config import get_settings
from life_agent.db.models import Conversation, Task, TaskRevision, User
from life_agent.db.session import get_session_factory
from life_agent.main import app


def _register_and_login(
    client: TestClient, username: str, password: str
) -> uuid.UUID:
    registered = client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    if registered.status_code != 201:
        raise RuntimeError(f"注册失败，HTTP {registered.status_code}。")
    logged_in = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    if logged_in.status_code != 200:
        raise RuntimeError(f"登录失败，HTTP {logged_in.status_code}。")
    return uuid.UUID(registered.json()["id"])


def _concurrent_revision(secret: str, task_id: str, budget: int, barrier: Barrier) -> int:
    settings = get_settings()
    with TestClient(app, base_url="http://testserver") as client:
        client.cookies.set(settings.session_cookie_name, secret)
        barrier.wait()
        response = client.post(
            f"/api/tasks/{task_id}/revisions",
            json={"expected_revision": 2, "conditions": {"budget": budget}},
        )
        return response.status_code


def check_tasks() -> int:
    settings = get_settings()
    if not settings.database_url.get_secret_value().startswith("postgresql+psycopg://"):
        print("失败: 真实任务检查只允许 PostgreSQL psycopg URL。")
        return 1

    suffix = secrets.token_hex(6)
    usernames = [f"task_a_{suffix}", f"task_b_{suffix}"]
    password = f"Local-check-{secrets.token_urlsafe(18)}"
    created_user_ids: list[uuid.UUID] = []

    try:
        with TestClient(app, base_url="http://testserver") as alice:
            created_user_ids.append(_register_and_login(alice, usernames[0], password))
            conversation = alice.post(
                "/api/conversations", json={"title": "versioned tasks"}
            )
            if conversation.status_code != 201:
                raise RuntimeError("A 创建对话失败。")
            conversation_id = conversation.json()["id"]
            shopping = alice.post(
                f"/api/conversations/{conversation_id}/tasks",
                json={
                    "domain": "shopping",
                    "goal": "Buy prizes",
                    "conditions": {"budget": 300, "quantity": 20},
                },
            )
            travel = alice.post(
                f"/api/conversations/{conversation_id}/tasks",
                json={
                    "domain": "travel",
                    "goal": "Plan trip",
                    "conditions": {"budget": 1200, "destination": "Hangzhou"},
                },
            )
            if shopping.status_code != 201 or travel.status_code != 201:
                raise RuntimeError("同一对话创建两个任务失败。")
            shopping_id = uuid.UUID(shopping.json()["id"])
            travel_id = uuid.UUID(travel.json()["id"])
            revised = alice.post(
                f"/api/tasks/{shopping_id}/revisions",
                json={"expected_revision": 1, "conditions": {"budget": 500}},
            )
            if revised.status_code != 201:
                raise RuntimeError("创建第二版条件失败。")
            alice_secret = alice.cookies[settings.session_cookie_name]

        with TestClient(app, base_url="http://testserver") as bob:
            created_user_ids.append(_register_and_login(bob, usernames[1], password))
            checks = [
                bob.get(f"/api/conversations/{conversation_id}/tasks"),
                bob.post(
                    f"/api/conversations/{conversation_id}/tasks",
                    json={"domain": "shopping", "goal": "Probe", "conditions": {}},
                ),
                bob.get(f"/api/tasks/{shopping_id}"),
                bob.get(f"/api/tasks/{shopping_id}/revisions"),
                bob.post(
                    f"/api/tasks/{shopping_id}/revisions",
                    json={"expected_revision": 2, "conditions": {"budget": 1}},
                ),
            ]
            if [response.status_code for response in checks] != [404] * 5:
                raise RuntimeError("B 对 A 的任务访问未统一返回 404。")

        with TestClient(app, base_url="http://testserver") as reconnected:
            reconnected.cookies.set(settings.session_cookie_name, alice_secret)
            shopping_current = reconnected.get(f"/api/tasks/{shopping_id}")
            travel_current = reconnected.get(f"/api/tasks/{travel_id}")
            history = reconnected.get(f"/api/tasks/{shopping_id}/revisions")
            if shopping_current.json()["conditions"]["budget"] != 500:
                raise RuntimeError("A 重连后未读到购物任务当前版本。")
            if travel_current.json()["conditions"]["budget"] != 1200:
                raise RuntimeError("购物修改污染了出行任务。")
            if [item["conditions"]["budget"] for item in history.json()["items"]] != [
                300,
                500,
            ]:
                raise RuntimeError("历史条件快照被覆盖。")

        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _concurrent_revision, alice_secret, shopping_id, budget, barrier
                )
                for budget in (600, 700)
            ]
            statuses = sorted(future.result() for future in futures)
        if statuses != [201, 409]:
            raise RuntimeError(f"并发更新结果不是一个成功一个冲突: {statuses}。")

        with get_session_factory()() as db:
            task_count = db.scalar(
                select(func.count())
                .select_from(Task)
                .join(Conversation)
                .where(Conversation.owner_id.in_(created_user_ids))
            )
            revision_count = db.scalar(
                select(func.count())
                .select_from(TaskRevision)
                .where(TaskRevision.task_id == shopping_id)
            )
        if task_count != 2 or revision_count != 3:
            raise RuntimeError("真实数据库任务或版本行数不正确。")

        print("真实 PostgreSQL 用户: 2")
        print("同一对话独立任务: 2")
        print("历史快照与重连读取: 成功")
        print("双用户所有权隔离: 成功")
        print("同基线并发结果: 201/409")
        print("购物任务版本行数: 3")
        print("状态: 成功")
        return 0
    except (KeyError, RuntimeError) as exc:
        print(f"失败: {exc}")
        return 1
    except SQLAlchemyError:
        print("失败: 任务存储不可用或未完成迁移。")
        return 1
    finally:
        if created_user_ids:
            try:
                with get_session_factory()() as db:
                    users = db.scalars(
                        select(User).where(User.id.in_(created_user_ids))
                    ).all()
                    for user in users:
                        db.delete(user)
                    db.commit()
            except SQLAlchemyError:
                pass


if __name__ == "__main__":
    raise SystemExit(check_tasks())