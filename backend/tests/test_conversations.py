"""Focused API checks for private conversations and message ownership."""

import secrets
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from life_agent.core.config import Settings, get_settings
from life_agent.db.base import Base
from life_agent.db.models import Message
from life_agent.db.session import get_db
from life_agent.main import app

PASSWORD = f"test-only-{secrets.token_urlsafe(18)}"


@pytest.fixture
def conversation_context() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def register_and_login(client: TestClient, username: str) -> None:
    registered = client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert registered.status_code == 201
    logged_in = client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert logged_in.status_code == 200


def create_conversation(client: TestClient, title: str) -> dict[str, object]:
    response = client.post("/api/conversations", json={"title": title})
    assert response.status_code == 201
    return response.json()


def test_two_accounts_cannot_access_each_others_conversations(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    alice_client, _factory = conversation_context
    register_and_login(alice_client, "alice")
    alice_conversation = create_conversation(alice_client, " Alice private ")
    alice_id = alice_conversation["id"]
    assert alice_conversation["title"] == "Alice private"

    with TestClient(app, base_url="http://testserver") as bob_client:
        register_and_login(bob_client, "bob")
        assert bob_client.get("/api/conversations").json()["items"] == []
        forbidden_requests = [
            bob_client.get(f"/api/conversations/{alice_id}"),
            bob_client.patch(
                f"/api/conversations/{alice_id}", json={"title": "stolen"}
            ),
            bob_client.post(
                f"/api/conversations/{alice_id}/messages",
                json={"client_message_id": "same-key", "content": "probe"},
            ),
            bob_client.get(f"/api/conversations/{alice_id}/messages"),
        ]
        assert [response.status_code for response in forbidden_requests] == [
            404,
            404,
            404,
            404,
        ]

        bob_conversation = create_conversation(bob_client, "Bob private")
        bob_id = bob_conversation["id"]

    assert alice_client.get(f"/api/conversations/{bob_id}").status_code == 404
    alice_list = alice_client.get("/api/conversations")
    assert [item["id"] for item in alice_list.json()["items"]] == [alice_id]


def test_message_retry_is_idempotent_and_conflicting_content_is_rejected(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Groceries")["id"]
    payload = {"client_message_id": "device-1-message-1", "content": "buy milk"}

    created = client.post(
        f"/api/conversations/{conversation_id}/messages", json=payload
    )
    retried = client.post(
        f"/api/conversations/{conversation_id}/messages", json=payload
    )
    conflict = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={**payload, "content": "buy bread"},
    )

    assert created.status_code == 201
    assert retried.status_code == 200
    assert retried.json() == created.json()
    assert conflict.status_code == 409
    assert "buy milk" not in conflict.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 1


def test_update_message_listing_order_and_new_client_restore(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "First title")["id"]
    secret = client.cookies["life_agent_session"]

    updated = client.patch(
        f"/api/conversations/{conversation_id}", json={"title": " New title "}
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "New title"
    for index in range(2):
        response = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "client_message_id": f"message-{index}",
                "content": f"content-{index}",
            },
        )
        assert response.status_code == 201

    with TestClient(app, base_url="http://testserver") as restored:
        restored.cookies.set("life_agent_session", secret)
        fetched = restored.get(f"/api/conversations/{conversation_id}")
        messages = restored.get(f"/api/conversations/{conversation_id}/messages")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "New title"
    assert [item["content"] for item in messages.json()["items"]] == [
        "content-0",
        "content-1",
    ]
    assert {item["role"] for item in messages.json()["items"]} == {"user"}


def test_rejects_anonymous_forged_cross_site_and_invalid_inputs(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = conversation_context
    assert client.get("/api/conversations").status_code == 401
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Private")["id"]

    forged_bodies = [
        {"title": "forged", "owner_id": "00000000-0000-0000-0000-000000000000"},
        {
            "client_message_id": "forged-role",
            "content": "fake response",
            "role": "assistant",
        },
        {
            "client_message_id": "forged-user",
            "content": "fake owner",
            "user_id": "00000000-0000-0000-0000-000000000000",
        },
    ]
    assert client.post("/api/conversations", json=forged_bodies[0]).status_code == 422
    for body in forged_bodies[1:]:
        assert client.post(
            f"/api/conversations/{conversation_id}/messages", json=body
        ).status_code == 422

    assert client.post("/api/conversations", json={"title": " "}).status_code == 422
    assert client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"client_message_id": "blank", "content": "   "},
    ).status_code == 422
    assert client.get("/api/conversations?limit=101").status_code == 422
    assert client.get(
        f"/api/conversations/{conversation_id}/messages?offset=-1"
    ).status_code == 422

    cross_site = client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "cross-site"},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert cross_site.status_code == 403
    assert client.get(f"/api/conversations/{conversation_id}").json()["title"] == (
        "Private"
    )