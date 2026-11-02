"""Verify migrated authentication behavior against the configured PostgreSQL."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from life_agent.core.config import get_settings
from life_agent.db.models import LoginSession, User
from life_agent.db.session import get_session_factory
from life_agent.main import app


def check_auth() -> int:
    settings = get_settings()
    if not settings.database_url.get_secret_value().startswith("postgresql+psycopg://"):
        print("失败: 真实认证检查只允许 PostgreSQL psycopg URL。")
        return 1

    suffix = secrets.token_hex(6)
    usernames = [f"auth_a_{suffix}", f"auth_b_{suffix}"]
    password = f"Local-check-{secrets.token_urlsafe(18)}"
    created_user_ids = []

    try:
        with TestClient(app, base_url="http://testserver") as first:
            for username in usernames:
                response = first.post(
                    "/api/auth/register",
                    json={"username": username, "password": password},
                )
                if response.status_code != 201:
                    raise RuntimeError(f"注册失败，HTTP {response.status_code}。")
                created_user_ids.append(response.json()["id"])

            duplicate = first.post(
                "/api/auth/register",
                json={"username": usernames[0], "password": password},
            )
            if duplicate.status_code != 409:
                raise RuntimeError("重复用户名未返回 409。")

            wrong = first.post(
                "/api/auth/login",
                json={"username": usernames[0], "password": password + "x"},
            )
            if wrong.status_code != 401:
                raise RuntimeError("错误密码未返回 401。")

            login = first.post(
                "/api/auth/login",
                json={"username": usernames[0], "password": password},
            )
            if login.status_code != 200:
                raise RuntimeError(f"登录失败，HTTP {login.status_code}。")
            secret = first.cookies[settings.session_cookie_name]

        with TestClient(app, base_url="http://testserver") as reconnected:
            reconnected.cookies.set(settings.session_cookie_name, secret)
            me = reconnected.get("/api/me")
            if me.status_code != 200 or me.json()["id"] != created_user_ids[0]:
                raise RuntimeError("客户端重新连接后未恢复正确身份。")

            with get_session_factory()() as db:
                user = db.scalar(select(User).where(User.username == usernames[0]))
                session = db.scalar(
                    select(LoginSession).where(LoginSession.user_id == user.id)
                ) if user else None
                if user is None or not user.password_hash.startswith("$argon2id$"):
                    raise RuntimeError("数据库未保存 Argon2id 密码哈希。")
                if password in user.password_hash:
                    raise RuntimeError("密码明文出现在持久化哈希中。")
                if session is None or session.token_hash == secret:
                    raise RuntimeError("数据库未仅保存会话秘密摘要。")

            logout = reconnected.post("/api/auth/logout")
            if logout.status_code != 204:
                raise RuntimeError("登出失败。")
            reconnected.cookies.set(settings.session_cookie_name, secret)
            if reconnected.get("/api/me").status_code != 401:
                raise RuntimeError("登出后旧 Cookie 仍然有效。")

        with TestClient(app, base_url="http://testserver") as expiring:
            expiring.post(
                "/api/auth/login",
                json={"username": usernames[1], "password": password},
            )
            with get_session_factory()() as db:
                session = db.scalar(
                    select(LoginSession)
                    .join(User)
                    .where(User.username == usernames[1])
                )
                if session is None:
                    raise RuntimeError("未找到待过期的服务端会话。")
                session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
            if expiring.get("/api/me").status_code != 401:
                raise RuntimeError("过期会话仍然有效。")

        print("注册用户: 2")
        print("重复用户名: 409")
        print("错误密码: 401")
        print("客户端重新连接身份恢复: 成功")
        print("密码存储: Argon2id 哈希")
        print("会话存储: 仅 SHA-256 摘要")
        print("登出吊销与到期拒绝: 成功")
        print("状态: 成功")
        return 0
    except (KeyError, RuntimeError) as exc:
        print(f"失败: {exc}")
        return 1
    except SQLAlchemyError:
        print("失败: 认证存储不可用或未完成迁移。")
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
    raise SystemExit(check_auth())