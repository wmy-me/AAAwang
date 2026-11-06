"""Focused API checks for private conversations and message ownership."""

import secrets
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from life_agent.core.config import Settings, get_settings
from life_agent.db.base import Base
from life_agent.db.models import Conversation, Message, Run, Task, TaskRevision
from life_agent.db.session import get_db
from life_agent.main import app
from life_agent.modules.chat.context import ContextBuilder
from life_agent.modules.chat.service import apply_conversation_route
from life_agent.modules.runs.service import claim_run

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


def test_conversation_turn_answers_without_creating_a_task_and_is_idempotent(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Chat")['id']

    payload = {"client_turn_id": "chat-1", "content": "你好"}
    created = client.post(f"/api/conversations/{conversation_id}/turns", json=payload)
    retried = client.post(f"/api/conversations/{conversation_id}/turns", json=payload)

    assert created.status_code == 201
    assert created.json()["task"] is None
    assert created.json()["run"]["task_id"] is None
    assert created.json()["run"]["execution_type"] == "conversation_route"
    assert created.json()["assistant_message"] is None
    assert retried.status_code == 200
    assert retried.json() == created.json()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 0
        assert db.scalar(select(func.count()).select_from(Run)) == 1
        assert db.scalar(select(func.count()).select_from(Message)) == 1


def test_context_builder_is_ordered_bounded_and_owner_scoped(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "context-alice")
    conversation_id = create_conversation(client, "Context")['id']
    for index, text in enumerate(("first preference", "second detail", "current turn")):
        assert client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"client_message_id": f"context-{index}", "content": text},
        ).status_code == 201
    with factory() as db:
        messages = list(db.scalars(select(Message).order_by(Message.created_at, Message.id)))
        owner_id = db.scalar(
            select(Conversation.owner_id).where(Conversation.id == uuid.UUID(conversation_id))
        )
        assert owner_id is not None
        context = ContextBuilder(max_messages=2, max_characters=100).build(
            db, owner_id, uuid.UUID(conversation_id), before_message_id=messages[-1].id
        )
        assert [item.content for item in context.messages] == ["first preference", "second detail"]
        assert context.truncated is False
        with pytest.raises(LookupError):
            ContextBuilder(max_messages=2, max_characters=100).build(
                db, uuid.uuid4(), uuid.UUID(conversation_id)
            )


def test_context_cursor_never_reads_messages_after_an_old_turn(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "context-cursor")
    conversation_id = create_conversation(client, "Cursor")['id']
    for index in range(20):
        assert client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"client_message_id": f"cursor-{index}", "content": f"turn-{index}"},
        ).status_code == 201
    with factory() as db:
        rows = list(db.scalars(select(Message).order_by(Message.created_at, Message.id)))
        owner_id = db.scalar(select(Conversation.owner_id).where(Conversation.id == uuid.UUID(conversation_id)))
        assert owner_id is not None
        context = ContextBuilder(max_messages=50, max_characters=1000).build(
            db, owner_id, uuid.UUID(conversation_id), before_message_id=rows[4].id
        )
        assert [item.content for item in context.messages] == [f"turn-{index}" for index in range(4)]
        assert "turn-19" not in context.as_prompt()


def test_context_does_not_split_or_skip_an_overlong_recent_turn(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "context-long")
    conversation_id = create_conversation(client, "Long")['id']
    for index, content in enumerate(("older fact", "x" * 80, "current")):
        assert client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"client_message_id": f"long-{index}", "content": content},
        ).status_code == 201
    with factory() as db:
        rows = list(db.scalars(select(Message).order_by(Message.created_at, Message.id)))
        owner_id = db.scalar(select(Conversation.owner_id).where(Conversation.id == uuid.UUID(conversation_id)))
        assert owner_id is not None
        context = ContextBuilder(max_messages=10, max_characters=40).build(
            db, owner_id, uuid.UUID(conversation_id), before_message_id=rows[-1].id
        )
        assert context.messages == ()
        assert context.truncated is True


def test_claimed_route_binds_a_task_only_after_worker_classification(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "route-worker")
    conversation_id = create_conversation(client, "Route")['id']
    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"client_turn_id": "route-task", "content": "给学生买奖品，预算 200 元"},
    )
    assert response.status_code == 201
    run_id = uuid.UUID(response.json()["run"]["id"])
    with factory() as db:
        claim = claim_run(db, "test-worker", 30, 3)
        assert claim is not None
        routed = apply_conversation_route(
            db, claim, {"intent": "task", "task_id": None, "reason": "test"}, {"model_requests": 1}
        )
        run = db.get(Run, run_id)
        assert run is not None
        assert routed.execution_type == "capability_decision"
        assert run.task_id is not None
        assert run.conditions["budget"] == 200.0


def test_conversation_turn_creates_one_shopping_task_and_run(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Shopping")['id']
    payload = {
        "client_turn_id": "shopping-1",
        "content": "给 25 个学生买奖品，预算 200 元",
    }
    created = client.post(f"/api/conversations/{conversation_id}/turns", json=payload)
    retried = client.post(f"/api/conversations/{conversation_id}/turns", json=payload)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["assistant_message"] is None
    assert body["task"] is None
    assert body["run"]["execution_type"] == "conversation_route"
    assert retried.status_code == 200
    assert retried.json() == body
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 0
        assert db.scalar(select(func.count()).select_from(Run)) == 1


def test_conversation_turn_updates_budget_and_creates_new_revision(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Shopping")['id']
    first = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={
            "client_turn_id": "shopping-budget-1",
            "content": "给学生买彩色铅笔，预算 200 元",
        },
    )
    assert first.status_code == 201, first.text

    second = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={
            "client_turn_id": "shopping-budget-2",
            "content": "预算改为 180 元",
        },
    )

    assert second.status_code == 201, second.text
    body = second.json()
    assert body["task"] is None
    assert body["run"]["execution_type"] == "conversation_route"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TaskRevision)) == 0

def test_conversation_uses_model_classification_not_keyword_prefilter(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Chat")['id']
    captured: dict[str, object] = {}

    def fake_classifier(settings, content, history, tasks):
        captured.update(
            {"content": content, "history": history, "tasks": tasks}
        )
        return {"intent": "chat", "task_id": None, "reason": "闲聊"}

    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"client_turn_id": "model-chat", "content": "给学生买奖品"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["task"] is None
    assert response.json()["run"]["task_id"] is None
    assert captured == {}
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 0


def test_conversation_asks_when_model_reports_ambiguous_task(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Shopping")['id']
    for index in range(2):
        created = client.post(
            f"/api/conversations/{conversation_id}/tasks",
            json={
                "domain": "shopping",
                "goal": f"task {index}",
                "conditions": {},
            },
        )
        assert created.status_code == 201, created.text

    def fake_classifier(settings, content, history, tasks):
        return {
            "intent": "ambiguous",
            "task_id": None,
            "clarification": "请说明要修改哪个任务。",
        }

    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"client_turn_id": "ambiguous-budget", "content": "预算改为 180 元"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task"] is None
    assert body["run"]["execution_type"] == "conversation_route"
    assert body["run"]["task_id"] is None
    assert body["run"]["decision"]["kind"] == "pending"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 2
        assert db.scalar(select(func.count()).select_from(Run)) == 1


def test_conversation_attaches_model_selected_existing_task(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Shopping")['id']
    created = client.post(
        f"/api/conversations/{conversation_id}/tasks",
        json={"domain": "shopping", "goal": "买彩色铅笔", "conditions": {}},
    )
    task_id = created.json()["id"]

    def fake_classifier(settings, content, history, tasks):
        return {"intent": "task", "task_id": task_id, "reason": "延续任务"}

    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"client_turn_id": "existing-task", "content": "继续看彩色铅笔"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task"] is None
    assert body["run"]["task_id"] is None
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 1


def test_conversation_rejects_guessed_task_when_multiple_tasks_exist(
    conversation_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = conversation_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client, "Shopping")['id']
    task_ids = []
    for index in range(2):
        created = client.post(
            f"/api/conversations/{conversation_id}/tasks",
            json={"domain": "shopping", "goal": f"task {index}", "conditions": {}},
        )
        task_ids.append(created.json()["id"])

    def fake_classifier(settings, content, history, tasks):
        return {
            "intent": "update_task",
            "task_id": task_ids[0],
            "reason": "模型猜测了第一个任务",
        }

    response = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"client_turn_id": "guessed-task", "content": "预算改为 150 元"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task"] is None
    assert body["run"]["task_id"] is None
    assert body["run"]["execution_type"] == "conversation_route"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TaskRevision)) == 2
