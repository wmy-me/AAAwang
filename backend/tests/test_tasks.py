"""Focused API checks for private tasks and immutable condition revisions."""

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
from life_agent.db.models import Task, TaskRevision
from life_agent.db.session import get_db
from life_agent.main import app
from life_agent.modules.forms.service import (
    FormValidationError,
    persist_model_proposal,
    validate_model_schema,
)

PASSWORD = f"test-only-{secrets.token_urlsafe(18)}"


def test_model_form_schema_normalizes_empty_item_unit() -> None:
    fields = validate_model_schema(
        [
            {
                "id": "item",
                "control": "short_text",
                "label": "口味/规格",
                "reason": "帮助筛选商品",
                "required": False,
                "unit": "",
            }
        ],
        {},
    )
    assert "unit" not in fields[0]

    with pytest.raises(FormValidationError, match="单位"):
        validate_model_schema(
            [
                {
                    "id": "people",
                    "control": "number",
                    "label": "人数",
                    "reason": "估算份数",
                    "unit": "件",
                }
            ],
            {},
        )


def test_model_form_schema_supports_registered_scene_controls() -> None:
    fields = validate_model_schema(
        [
            {
                "id": "color",
                "control": "single_select",
                "label": "颜色",
                "reason": "筛选偏好",
                "options": ["黑色", "蓝色", "黄色", "红色", "其他"],
            },
        ],
        {},
        "shopping",
    )
    assert fields[0]["control"] == "single_select"
    travel_fields = validate_model_schema(
        [{"id": "activity_types", "control": "multi_select", "label": "活动类型", "reason": "筛选活动", "options": ["美食", "展览", "户外", "亲子", "文化"]}],
        {},
        "travel",
    )
    assert travel_fields[0]["control"] == "multi_select"
    with pytest.raises(FormValidationError, match="标记"):
        validate_model_schema(
            [{"id": "color", "control": "single_select", "label": "<script>", "reason": "x", "options": ["黑色", "蓝色", "黄色", "红色", "其他"]}],
            {},
            "shopping",
        )


def test_model_form_schema_accepts_unregistered_business_fields_with_bounds() -> None:
    fields = validate_model_schema(
        [
            {
                "id": "fabric_type",
                "control": "single_select",
                "label": "面料偏好",
                "reason": "帮助筛选适合通勤的雨衣",
                "options": ["轻薄", "防水", "透气"],
            },
            {
                "id": "activity_duration",
                "control": "number",
                "label": "活动时长",
                "reason": "用于安排周末活动",
                "unit": "小时",
                "min_value": 1,
                "max_value": 24,
            },
        ],
        {},
        "shopping",
    )
    assert {field["id"] for field in fields} == {"fabric_type", "activity_duration"}
    with pytest.raises(FormValidationError, match="选项"):
        validate_model_schema(
            [{"id": "fabric_type", "control": "single_select", "label": "面料", "reason": "筛选", "options": ["防水"]}],
            {},
            "shopping",
        )
    with pytest.raises(FormValidationError, match="保留"):
        validate_model_schema(
            [{"id": "api_key", "control": "short_text", "label": "密钥", "reason": "x"}],
            {},
            "shopping",
        )


@pytest.fixture
def task_context() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
    assert client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    ).status_code == 201
    assert client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    ).status_code == 200


def create_conversation(client: TestClient, title: str = "Planning") -> str:
    response = client.post("/api/conversations", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


def create_task(
    client: TestClient,
    conversation_id: str,
    domain: str,
    goal: str,
    conditions: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        f"/api/conversations/{conversation_id}/tasks",
        json={"domain": domain, "goal": goal, "conditions": conditions},
    )
    assert response.status_code == 201
    return response.json()


def test_two_tasks_keep_independent_conditions_and_immutable_history(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = task_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client)
    shopping = create_task(
        client,
        conversation_id,
        "shopping",
        "Buy class prizes",
        {"budget": 300, "people": 20, "quantity": 20},
    )
    travel = create_task(
        client,
        conversation_id,
        "travel",
        "Plan weekend trip",
        {"budget": 1200, "destination": "Hangzhou", "people": 2},
    )

    revised = client.post(
        f"/api/tasks/{shopping['id']}/revisions",
        json={
            "expected_revision": 1,
            "conditions": {"budget": 500, "people": 20, "quantity": 20},
            "change_note": "Increase prize budget",
        },
    )
    assert revised.status_code == 201
    assert revised.json()["revision"] == 2
    assert client.get(f"/api/tasks/{shopping['id']}").json()["conditions"][
        "budget"
    ] == 500
    assert client.get(f"/api/tasks/{travel['id']}").json()["conditions"][
        "budget"
    ] == 1200

    history = client.get(f"/api/tasks/{shopping['id']}/revisions").json()["items"]
    assert [item["revision"] for item in history] == [1, 2]
    assert [item["conditions"]["budget"] for item in history] == [300, 500]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 2
        assert db.scalar(select(func.count()).select_from(TaskRevision)) == 3


def test_stale_revision_conflicts_and_equal_snapshot_creates_new_revision(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = task_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client)
    task = create_task(
        client,
        conversation_id,
        "shopping",
        "Buy snacks",
        {"budget": 100, "quantity": 10},
    )
    same_snapshot = client.post(
        f"/api/tasks/{task['id']}/revisions",
        json={"expected_revision": 1, "conditions": task["conditions"]},
    )
    stale = client.post(
        f"/api/tasks/{task['id']}/revisions",
        json={"expected_revision": 1, "conditions": {"budget": 120}},
    )

    assert same_snapshot.status_code == 201
    assert same_snapshot.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == 2
    history = client.get(f"/api/tasks/{task['id']}/revisions").json()["items"]
    assert len(history) == 2


def test_other_account_cannot_probe_or_modify_tasks(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    alice, _factory = task_context
    register_and_login(alice, "alice")
    conversation_id = create_conversation(alice)
    task = create_task(
        alice,
        conversation_id,
        "travel",
        "Private trip",
        {"destination": "Suzhou"},
    )
    secret = alice.cookies["life_agent_session"]

    with TestClient(app, base_url="http://testserver") as bob:
        register_and_login(bob, "bob")
        requests = [
            bob.get(f"/api/conversations/{conversation_id}/tasks"),
            bob.post(
                f"/api/conversations/{conversation_id}/tasks",
                json={"domain": "shopping", "goal": "Probe", "conditions": {}},
            ),
            bob.get(f"/api/tasks/{task['id']}"),
            bob.get(f"/api/tasks/{task['id']}/revisions"),
            bob.post(
                f"/api/tasks/{task['id']}/revisions",
                json={"expected_revision": 1, "conditions": {"destination": "Wuxi"}},
            ),
        ]
        assert [response.status_code for response in requests] == [404] * 5

    with TestClient(app, base_url="http://testserver") as restored:
        restored.cookies.set("life_agent_session", secret)
        response = restored.get(f"/api/tasks/{task['id']}")
    assert response.status_code == 200
    assert response.json()["conditions"] == {"destination": "Suzhou"}


def test_rejects_invalid_conditions_forged_identity_and_cross_site_write(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = task_context
    assert client.get("/api/tasks/00000000-0000-0000-0000-000000000000").status_code == 401
    register_and_login(client, "alice")
    conversation_id = create_conversation(client)

    invalid_payloads = [
        {"domain": "finance", "goal": "Invalid", "conditions": {}},
        {"domain": "shopping", "goal": "Invalid", "conditions": {"budget": -1}},
        {"domain": "shopping", "goal": "Invalid", "conditions": {"budget": True}},
        {"domain": "shopping", "goal": "Invalid", "conditions": {"people": True}},
        {"domain": "shopping", "goal": "Invalid", "conditions": {"destination": "X"}},
        {"domain": "travel", "goal": "Invalid", "conditions": {"people": 1.5}},
        {
            "domain": "travel",
            "goal": "Invalid",
            "conditions": {"start_date": "2026-12-10", "end_date": "2026-12-01"},
        },
        {"domain": "shopping", "goal": "Forged", "conditions": {}, "owner_id": "x"},
    ]
    for payload in invalid_payloads:
        assert client.post(
            f"/api/conversations/{conversation_id}/tasks", json=payload
        ).status_code == 422

    task = create_task(
        client,
        conversation_id,
        "travel",
        "Trip",
        {"destination": "Nanjing"},
    )
    assert client.post(
        f"/api/tasks/{task['id']}/revisions",
        json={
            "expected_revision": 1,
            "conditions": {"destination": "Wuxi"},
            "user_id": "00000000-0000-0000-0000-000000000000",
        },
    ).status_code == 422
    assert client.post(
        f"/api/tasks/{task['id']}/revisions",
        json={"expected_revision": 1, "conditions": {"quantity": 2}},
    ).status_code == 422
    assert client.get(f"/api/tasks/{task['id']}/revisions?limit=101").status_code == 422

    cross_site = client.post(
        f"/api/tasks/{task['id']}/revisions",
        json={"expected_revision": 1, "conditions": {"destination": "Wuxi"}},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert cross_site.status_code == 403
    assert client.get(f"/api/tasks/{task['id']}").json()["current_revision"] == 1


def test_dynamic_form_is_bounded_idempotent_and_creates_revision(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = task_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client)
    task = create_task(client, conversation_id, "shopping", "Buy gifts", {})

    proposal = client.get(f"/api/tasks/{task['id']}/form")
    assert proposal.status_code == 200
    body = proposal.json()
    assert {field["id"] for field in body["schema"]} == {
        "item",
        "people",
        "quantity",
        "budget",
    }
    assert body["status"] == "pending"

    invalid = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": body["id"],
            "expected_revision": 1,
            "client_request_id": "form-1",
            "values": {"unknown": "x"},
        },
    )
    assert invalid.status_code == 422

    submitted = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": body["id"],
            "expected_revision": 1,
            "client_request_id": "form-1",
            "values": {"people": 25, "budget": 200},
        },
    )
    assert submitted.status_code == 201
    submitted_body = submitted.json()
    assert submitted_body["task"]["current_revision"] == 2
    assert submitted_body["task"]["conditions"] == {"people": 25, "budget": 200}
    assert submitted_body["message"]["client_message_id"] == "form-1"
    assert submitted_body["run"]["execution_type"] == "capability_decision"
    assert submitted_body["run"]["goal"] == "Buy gifts"

    repeated = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": body["id"],
            "expected_revision": 1,
            "client_request_id": "form-1",
            "values": {"people": 25, "budget": 200},
        },
    )
    assert repeated.status_code == 201
    assert repeated.json()["message"]["id"] == submitted_body["message"]["id"]
    assert repeated.json()["run"]["id"] == submitted_body["run"]["id"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TaskRevision)) == 2


def test_dynamic_form_merges_confirmed_values_with_existing_conditions(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = task_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client)
    task = create_task(
        client,
        conversation_id,
        "shopping",
        "Buy gifts",
        {"item": "彩色铅笔", "people": 25},
    )
    proposal = client.get(f"/api/tasks/{task['id']}/form").json()
    assert {field["id"] for field in proposal["schema"]} == {"quantity", "budget"}
    submitted = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": proposal["id"],
            "expected_revision": 1,
            "client_request_id": "merge-values",
            "values": {"quantity": 25, "budget": 200},
        },
    )
    assert submitted.status_code == 201, submitted.json()
    assert submitted.json()["task"]["conditions"] == {
        "item": "彩色铅笔",
        "people": 25,
        "quantity": 25,
        "budget": 200,
    }
    assert submitted.json()["run"]["goal"] == "Buy gifts"


def test_dynamic_form_custom_proposal_validates_values_before_revision(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = task_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client)
    task = create_task(client, conversation_id, "shopping", "Choose a raincoat", {})
    custom_schema = [
        {
            "id": "fabric_type",
            "control": "single_select",
            "label": "面料",
            "reason": "筛选通勤面料",
            "options": ["尼龙", "涤纶", "牛津布"],
        },
        {
            "id": "weather_preferences",
            "control": "multi_select",
            "label": "天气偏好",
            "reason": "筛选适合天气",
            "options": ["小雨", "大雨", "大风"],
        },
    ]
    with factory() as db:
        proposal = persist_model_proposal(db, uuid.UUID(task["id"]), 1, custom_schema)
        assert proposal is not None
        db.commit()
        proposal_id = str(proposal.id)

    invalid_option = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": proposal_id,
            "expected_revision": 1,
            "client_request_id": "custom-invalid-option",
            "values": {"fabric_type": "皮革", "weather_preferences": ["小雨"]},
        },
    )
    assert invalid_option.status_code == 422
    assert client.get(f"/api/tasks/{task['id']}").json()["current_revision"] == 1

    invalid_unknown = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": proposal_id,
            "expected_revision": 1,
            "client_request_id": "custom-invalid-unknown",
            "values": {
                "fabric_type": "尼龙",
                "weather_preferences": ["小雨"],
                "owner_id": "forged",
            },
        },
    )
    assert invalid_unknown.status_code == 422
    assert client.get(f"/api/tasks/{task['id']}").json()["current_revision"] == 1

    submitted = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": proposal_id,
            "expected_revision": 1,
            "client_request_id": "custom-valid",
            "values": {
                "fabric_type": "尼龙",
                "weather_preferences": ["小雨", "大风"],
            },
        },
    )
    assert submitted.status_code == 201, submitted.json()
    assert submitted.json()["task"]["conditions"] == {
        "fabric_type": "尼龙",
        "weather_preferences": ["小雨", "大风"],
    }


def test_dynamic_form_rejects_stale_revision_and_cross_account_access(
    task_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = task_context
    register_and_login(client, "alice")
    conversation_id = create_conversation(client)
    task = create_task(client, conversation_id, "shopping", "Buy gifts", {})
    proposal = client.get(f"/api/tasks/{task['id']}/form").json()
    revised = client.post(
        f"/api/tasks/{task['id']}/revisions",
        json={"expected_revision": 1, "conditions": {"people": 2}},
    )
    assert revised.status_code == 201
    stale = client.post(
        f"/api/tasks/{task['id']}/form/submit",
        json={
            "proposal_id": proposal["id"],
            "expected_revision": 1,
            "client_request_id": "stale-form",
            "values": {"budget": 100},
        },
    )
    assert stale.status_code == 409
    assert (
        client.get(f"/api/tasks/{task['id']}/form/{proposal['id']}").status_code
        == 200
    )

    with TestClient(app, base_url="http://testserver") as bob:
        register_and_login(bob, "bob")
        assert bob.get(f"/api/tasks/{task['id']}/form").status_code == 404
        assert (
            bob.get(f"/api/tasks/{task['id']}/form/{proposal['id']}").status_code
            == 404
        )