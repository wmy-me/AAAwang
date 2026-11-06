"""Focused boundaries for explicit, owner-scoped preference memory."""

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from life_agent.db.base import Base
from life_agent.db.models import User
from life_agent.modules.memory import apply_memory_action, relevant_preferences


def _db() -> tuple[Session, uuid.UUID, uuid.UUID]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    first, second = User(username="alice", password_hash="x"), User(username="bob", password_hash="x")
    db.add_all((first, second)); db.commit()
    return db, first.id, second.id


def test_preference_is_owner_scoped_relevant_and_deleted() -> None:
    db, alice, bob = _db()
    action = {"memory_action": "remember", "memory_category": "diet", "memory_key": "饮食偏好", "memory_value": "不吃辣"}
    assert "已记住" in apply_memory_action(db, alice, uuid.uuid4(), action)
    assert [item.content for item in relevant_preferences(db, alice, "推荐一家餐厅")] == ["不吃辣"]
    assert relevant_preferences(db, bob, "推荐一家餐厅") == []
    forget = {**action, "memory_action": "forget"}
    assert "已忘记" in apply_memory_action(db, alice, uuid.uuid4(), forget)
    assert relevant_preferences(db, alice, "推荐一家餐厅") == []
    assert "暂无" in apply_memory_action(db, alice, uuid.uuid4(), {"memory_action": "list"})


def test_preference_rejects_sensitive_content_and_task_budget_is_not_memory() -> None:
    db, alice, _bob = _db()
    sensitive = {"memory_action": "remember", "memory_category": "general", "memory_key": "密码", "memory_value": "abc"}
    assert "不能保存" in apply_memory_action(db, alice, uuid.uuid4(), sensitive)
    assert relevant_preferences(db, alice, "预算 200 元") == []
