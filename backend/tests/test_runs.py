"""Focused API and ownership checks for persistent task runs."""

import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from life_agent.core.config import Settings, get_settings
from life_agent.db.base import Base
from life_agent.db.models import Run, RunEvent, Task, User
from life_agent.db.session import get_db
from life_agent.main import app
from life_agent.modules.runs.service import claim_run, complete_claim

PASSWORD = f"test-only-{secrets.token_urlsafe(18)}"


@pytest.fixture
def run_context() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

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


def create_task(client: TestClient) -> dict[str, object]:
    conversation = client.post("/api/conversations", json={"title": "Planning"})
    assert conversation.status_code == 201
    response = client.post(
        f"/api/conversations/{conversation.json()['id']}/tasks",
        json={
            "domain": "shopping",
            "goal": "Buy class prizes",
            "conditions": {"budget": 300, "quantity": 20},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_run_is_idempotent_and_keeps_old_revision_snapshot(
    run_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = run_context
    register_and_login(client, "alice")
    task = create_task(client)
    payload = {"expected_revision": 1, "idempotency_key": "run-1"}
    first = client.post(f"/api/tasks/{task['id']}/runs", json=payload)
    retry = client.post(f"/api/tasks/{task['id']}/runs", json=payload)
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert first.json()["task_revision_id"]

    revised = client.post(
        f"/api/tasks/{task['id']}/revisions",
        json={"expected_revision": 1, "conditions": {"budget": 500}},
    )
    assert revised.status_code == 201
    stored = client.get(f"/api/runs/{first.json()['id']}")
    assert stored.status_code == 200
    assert stored.json()["revision"] == 1
    assert stored.json()["conditions"] == {"budget": 300, "quantity": 20}

    stale = client.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": "run-2"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == 2


def test_runs_are_private_and_cancel_is_idempotent(
    run_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    alice, _factory = run_context
    register_and_login(alice, "alice")
    task = create_task(alice)
    created = alice.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": "private"},
    )
    run_id = created.json()["id"]

    with TestClient(app, base_url="http://testserver") as bob:
        register_and_login(bob, "bob")
        assert bob.get(f"/api/tasks/{task['id']}/runs").status_code == 404
        assert bob.get(f"/api/runs/{run_id}").status_code == 404
        assert bob.post(f"/api/runs/{run_id}/cancel").status_code == 404

    cancelled = alice.post(f"/api/runs/{run_id}/cancel")
    repeated = alice.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == repeated.status_code == 200
    assert cancelled.json()["status"] == repeated.json()["status"] == "cancelled"


def test_fencing_rejects_late_worker_completion(
    run_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = run_context
    register_and_login(client, "alice")
    task = create_task(client)
    created = client.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": "lease"},
    )
    run_id = created.json()["id"]

    with factory() as db:
        worker_one = claim_run(db, "worker-one", 30, 3)
        assert worker_one is not None
        db.execute(
            Run.__table__.update()
            .where(Run.id == uuid.UUID(run_id))
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        db.commit()
        worker_two = claim_run(db, "worker-two", 30, 3)
        assert worker_two is not None
        assert worker_two.fencing_token > worker_one.fencing_token
        assert complete_claim(db, worker_one, {"late": True}) is False
        assert complete_claim(db, worker_two, {"runner": "diagnostic"}) is True
        stored = db.scalar(select(Run).where(Run.id == uuid.UUID(run_id)))
        assert stored is not None
        assert stored.status == "completed"
        assert stored.worker_id == "worker-two"


def test_run_input_and_cross_site_write_are_rejected(
    run_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = run_context
    register_and_login(client, "alice")
    task = create_task(client)
    assert client.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": True},
    ).status_code == 422
    assert client.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 0, "idempotency_key": "bad"},
    ).status_code == 422
    assert client.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": "cross"},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    ).status_code == 403
    with _factory() as db:
        assert db.scalar(select(User).where(User.username == "alice")) is not None
        assert db.scalar(select(Task).where(Task.id == uuid.UUID(task["id"]))) is not None


def test_run_events_are_ordered_private_and_idempotent(
    run_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    alice, factory = run_context
    register_and_login(alice, "alice")
    task = create_task(alice)
    created = alice.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": "events"},
    )
    run_id = created.json()["id"]
    assert alice.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert alice.post(f"/api/runs/{run_id}/cancel").status_code == 200

    listed = alice.get(f"/api/runs/{run_id}/events?after=0&limit=1")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["event_type"] == "run.queued"
    cursor = listed.json()["next_after"]
    remaining = alice.get(f"/api/runs/{run_id}/events?after={cursor}")
    assert [item["event_type"] for item in remaining.json()["items"]] == [
        "run.cancelled"
    ]
    assert remaining.json()["next_after"] == 2
    with factory() as db:
        assert db.scalar(select(Run).where(Run.id == uuid.UUID(run_id))).status == "cancelled"

    with TestClient(app, base_url="http://testserver") as bob:
        register_and_login(bob, "bob")
        assert bob.get(f"/api/runs/{run_id}/events").status_code == 404


def test_completed_run_events_can_be_replayed_over_sse(
    run_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = run_context
    register_and_login(client, "alice")
    task = create_task(client)
    created = client.post(
        f"/api/tasks/{task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": "sse"},
    )
    run_id = created.json()["id"]
    with factory() as db:
        claim = claim_run(db, "worker-one", 30, 3)
        assert claim is not None
        assert complete_claim(db, claim, {"runner": "diagnostic"})

    with client.stream("GET", f"/api/runs/{run_id}/events/stream") as response:
        assert response.status_code == 200
        body = response.read().decode()
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run.queued" in body
    assert "event: run.running" in body
    assert "event: run.completed" in body
    assert "id: 3" in body

    replay = client.get(f"/api/runs/{run_id}/events/stream?after=2")
    assert replay.status_code == 200


def test_deleting_user_cascades_runs_and_events_without_cross_user_delete(
    run_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    alice, factory = run_context
    register_and_login(alice, "alice")
    alice_task = create_task(alice)
    alice_run = alice.post(
        f"/api/tasks/{alice_task['id']}/runs",
        json={"expected_revision": 1, "idempotency_key": "delete-alice"},
    ).json()
    assert alice.post(f"/api/runs/{alice_run['id']}/cancel").status_code == 200

    with TestClient(app, base_url="http://testserver") as bob:
        register_and_login(bob, "bob")
        bob_task = create_task(bob)
        bob_run = bob.post(
            f"/api/tasks/{bob_task['id']}/runs",
            json={"expected_revision": 1, "idempotency_key": "keep-bob"},
        ).json()

    with factory() as db:
        before_runs = list(db.scalars(select(Run).order_by(Run.created_at)))
        assert len(before_runs) == 2
        assert {run.owner_id for run in before_runs}.__len__() == 2
        assert {str(run.id) for run in before_runs} == {alice_run["id"], bob_run["id"]}
        assert len({run.task_id for run in before_runs}) == 2
        assert len({run.task_revision_id for run in before_runs}) == 2
        alice_user = db.scalar(select(User).where(User.username == "alice"))
        assert alice_user is not None
        db.delete(alice_user)
        db.commit()
        assert db.scalar(select(Run).where(Run.id == uuid.UUID(alice_run["id"]))) is None
        assert db.scalar(
            select(RunEvent).where(RunEvent.run_id == uuid.UUID(alice_run["id"]))
        ) is None
        assert db.scalar(select(Run).where(Run.id == uuid.UUID(bob_run["id"]))) is not None
