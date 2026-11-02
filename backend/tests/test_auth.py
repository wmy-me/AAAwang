"""Focused API checks for account and server-side session boundaries."""

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from life_agent.core.config import Settings, get_settings
from life_agent.db.base import Base
from life_agent.db.models import LoginSession, User
from life_agent.db.session import get_db
from life_agent.main import app

PASSWORD = f"test-only-{secrets.token_urlsafe(18)}"


@pytest.fixture
def auth_context() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        session_cookie_secure=False,
        trusted_origins=["http://testserver"],
    )

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, base_url="http://testserver") as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200


def test_register_login_me_and_logout_revoke_old_cookie(
    auth_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = auth_context
    registered = register(client, "Alice")
    login(client, "alice")
    secret = client.cookies["life_agent_session"]

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == registered

    with factory() as db:
        user = db.scalar(select(User).where(User.username == "alice"))
        stored_session = db.scalar(select(LoginSession))
        assert user is not None and user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        assert stored_session is not None and stored_session.token_hash != secret

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 204
    assert "Max-Age=0" in logout.headers["set-cookie"]
    client.cookies.set("life_agent_session", secret)
    assert client.get("/api/me").status_code == 401


def test_two_clients_keep_distinct_identities_and_reject_forged_id(
    auth_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    first, _factory = auth_context
    alice = register(first, "alice")
    bob = register(first, "bob")
    login(first, "alice")
    with TestClient(app, base_url="http://testserver") as second:
        login(second, "bob")
        assert first.get("/api/me").json()["id"] == alice["id"]
        assert second.get("/api/me").json()["id"] == bob["id"]
        forged = second.post(
            "/api/auth/login",
            json={"username": "bob", "password": PASSWORD, "user_id": alice["id"]},
        )
        assert forged.status_code == 422
        assert second.get("/api/me").json()["id"] == bob["id"]


def test_duplicate_wrong_password_anonymous_and_expired_session(
    auth_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = auth_context
    register(client, "alice")
    assert client.post(
        "/api/auth/register", json={"username": "ALICE", "password": PASSWORD}
    ).status_code == 409
    assert client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "this password is wrong"},
    ).status_code == 401
    assert client.get("/api/me").status_code == 401

    login(client, "alice")
    with factory() as db:
        session = db.scalar(select(LoginSession))
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/me").status_code == 401


def test_cookie_attributes_and_cross_site_state_changes(
    auth_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = auth_context
    register(client, "alice")
    response = client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie

    cross_site_headers = {
        "Origin": "https://evil.example",
        "Sec-Fetch-Site": "cross-site",
    }
    requests = [
        client.post(
            "/api/auth/register",
            json={"username": "mallory", "password": PASSWORD},
            headers=cross_site_headers,
        ),
        client.post(
            "/api/auth/login",
            json={"username": "alice", "password": PASSWORD},
            headers=cross_site_headers,
        ),
        client.post("/api/auth/logout", headers=cross_site_headers),
    ]
    assert [response.status_code for response in requests] == [403, 403, 403]
    assert client.get("/api/me").status_code == 200

    secure_settings = Settings(
        app_env="production",
        session_cookie_secure=True,
        trusted_origins=["https://app.example"],
    )
    app.dependency_overrides[get_settings] = lambda: secure_settings
    secure_login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
        headers={"Origin": "https://app.example"},
    )
    assert secure_login.status_code == 200
    assert "Secure" in secure_login.headers["set-cookie"]


def test_cookie_security_configuration_rejects_unsafe_production() -> None:
    with pytest.raises(ValueError, match="生产环境"):
        Settings(app_env="production", session_cookie_secure=False)
    with pytest.raises(ValueError, match="SameSite=None"):
        Settings(session_cookie_samesite="none", session_cookie_secure=False)