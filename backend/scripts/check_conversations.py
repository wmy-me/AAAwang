"""Verify private conversation ownership against the configured PostgreSQL."""

import secrets

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from life_agent.core.config import get_settings
from life_agent.db.models import Conversation, Message, User
from life_agent.db.session import get_session_factory
from life_agent.main import app


def _register_and_login(client: TestClient, username: str, password: str) -> str:
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
    return registered.json()["id"]


def check_conversations() -> int:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    if not database_url.startswith("postgresql+psycopg://"):
        print("失败: 真实对话检查只允许 PostgreSQL psycopg URL。")
        return 1

    suffix = secrets.token_hex(6)
    usernames = [f"conversation_a_{suffix}", f"conversation_b_{suffix}"]
    password = f"Local-check-{secrets.token_urlsafe(18)}"
    created_user_ids: list[str] = []

    try:
        with TestClient(app, base_url="http://testserver") as alice:
            created_user_ids.append(_register_and_login(alice, usernames[0], password))
            created = alice.post(
                "/api/conversations", json={"title": "private alpha"}
            )
            if created.status_code != 201:
                raise RuntimeError(f"创建对话失败，HTTP {created.status_code}。")
            alice_conversation_id = created.json()["id"]
            message_payload = {
                "client_message_id": f"client-{suffix}",
                "content": "private message alpha",
            }
            first_message = alice.post(
                f"/api/conversations/{alice_conversation_id}/messages",
                json=message_payload,
            )
            retried_message = alice.post(
                f"/api/conversations/{alice_conversation_id}/messages",
                json=message_payload,
            )
            conflict = alice.post(
                f"/api/conversations/{alice_conversation_id}/messages",
                json={**message_payload, "content": "different private content"},
            )
            if first_message.status_code != 201 or retried_message.status_code != 200:
                raise RuntimeError("相同消息重试未返回已持久化消息。")
            if first_message.json()["id"] != retried_message.json()["id"]:
                raise RuntimeError("相同消息重试产生了不同消息 ID。")
            if conflict.status_code != 409:
                raise RuntimeError("相同客户端 ID 的不同正文未返回 409。")
            alice_secret = alice.cookies[settings.session_cookie_name]

        with TestClient(app, base_url="http://testserver") as bob:
            created_user_ids.append(_register_and_login(bob, usernames[1], password))
            if bob.get("/api/conversations").json()["items"]:
                raise RuntimeError("B 的列表出现了 A 的私有对话。")
            checks = [
                bob.get(f"/api/conversations/{alice_conversation_id}"),
                bob.patch(
                    f"/api/conversations/{alice_conversation_id}",
                    json={"title": "unauthorized"},
                ),
                bob.post(
                    f"/api/conversations/{alice_conversation_id}/messages",
                    json=message_payload,
                ),
                bob.get(f"/api/conversations/{alice_conversation_id}/messages"),
            ]
            if [response.status_code for response in checks] != [404, 404, 404, 404]:
                raise RuntimeError("B 对 A 的读取或写入未统一返回 404。")
            bob_conversation = bob.post(
                "/api/conversations", json={"title": "private beta"}
            )
            if bob_conversation.status_code != 201:
                raise RuntimeError("B 创建私有对话失败。")
            bob_conversation_id = bob_conversation.json()["id"]

        with TestClient(app, base_url="http://testserver") as reconnected:
            reconnected.cookies.set(settings.session_cookie_name, alice_secret)
            restored = reconnected.get(
                f"/api/conversations/{alice_conversation_id}/messages"
            )
            if restored.status_code != 200:
                raise RuntimeError("新客户端未能读取 A 的持久化消息。")
            if [item["content"] for item in restored.json()["items"]] != [
                message_payload["content"]
            ]:
                raise RuntimeError("新客户端读取的消息内容或数量不正确。")
            if (
                reconnected.get(f"/api/conversations/{bob_conversation_id}").status_code
                != 404
            ):
                raise RuntimeError("A 能读取 B 的私有对话。")

        with get_session_factory()() as db:
            conversation_count = db.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.owner_id.in_(created_user_ids))
            )
            message_count = db.scalar(
                select(func.count())
                .select_from(Message)
                .join(Conversation)
                .where(Conversation.owner_id.in_(created_user_ids))
            )
        if conversation_count != 2 or message_count != 1:
            raise RuntimeError("数据库中的对话或幂等消息行数不正确。")

        print("真实 PostgreSQL 用户: 2")
        print("私有对话: 2")
        print("跨客户端持久化读取: 成功")
        print("双向所有权隔离: 成功")
        print("同文重试/异文冲突: 200/409")
        print("持久化消息行数: 1")
        print("状态: 成功")
        return 0
    except (KeyError, RuntimeError) as exc:
        print(f"失败: {exc}")
        return 1
    except SQLAlchemyError:
        print("失败: 对话存储不可用或未完成迁移。")
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
    raise SystemExit(check_conversations())