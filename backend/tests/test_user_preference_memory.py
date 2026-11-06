"""Focused Mem0 adapter boundaries; the fake replaces model/vector I/O only."""

import uuid

import pytest

from life_agent.core.budget import BudgetLimits, RunBudget
from life_agent.modules.memory.service import MemoryUnavailableError, Mem0PreferenceService


class FakeMem0:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {}
        self.add_calls = 0
        self.fail_search = False

    def add(self, messages, *, user_id, metadata, **_kwargs):
        self.add_calls += 1
        item_id = str(uuid.uuid4())
        self.items[item_id] = {"id": item_id, "memory": messages[0]["content"], "metadata": {**metadata, "user_id": user_id}}
        return {"results": [self.items[item_id]]}

    def get_all(self, *, filters, **_kwargs):
        return {"results": [item for item in self.items.values() if item["metadata"]["user_id"] == filters["user_id"]]}

    def search(self, _query, *, filters, **_kwargs):
        if self.fail_search:
            raise RuntimeError("embedding unavailable")
        return self.get_all(filters=filters)

    def update(self, memory_id, *, data=None, metadata=None, **_kwargs):
        self.items[memory_id]["memory"] = data
        self.items[memory_id]["metadata"].update(metadata or {})

    def delete(self, memory_id):
        del self.items[memory_id]


def _action(operation: str, value: str = "不吃辣") -> dict[str, str]:
    return {"memory_action": operation, "memory_category": "diet", "memory_key": "饮食偏好", "memory_value": value}


def test_explicit_preference_round_trip_is_owner_scoped_and_retry_safe() -> None:
    client, service = FakeMem0(), None
    service = Mem0PreferenceService(client)
    alice, bob, message_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    budget = RunBudget()
    assert "已记住" in service.apply(alice, message_id, _action("remember"), budget)
    assert budget.model_requests == 1
    assert "不吃辣" in service.relevant(alice, "推荐餐厅")[0].content
    assert service.relevant(bob, "推荐餐厅") == []
    # A worker retry of the same durable message does not invoke Mem0 add again.
    assert "已记住" in service.apply(alice, message_id, _action("remember"), budget)
    assert client.add_calls == 1
    assert "已更新" in service.apply(alice, uuid.uuid4(), _action("update", "微辣"), budget)
    assert "已忘记" in service.apply(alice, uuid.uuid4(), {**_action("forget", "微辣"), "memory_value": None}, budget)
    assert service.relevant(alice, "推荐餐厅") == []


def test_sensitive_and_temporary_task_conditions_are_not_written() -> None:
    client = FakeMem0()
    service = Mem0PreferenceService(client)
    owner = uuid.uuid4()
    assert "不能保存" in service.apply(owner, uuid.uuid4(), {**_action("remember"), "memory_key": "密码", "memory_value": "abc"}, RunBudget())
    # A task budget never reaches this explicit-memory adapter without a memory action.
    assert "没有找到" in service.apply(owner, uuid.uuid4(), {**_action("task"), "memory_value": "预算 200 元"}, RunBudget())
    assert client.add_calls == 0
    assert service.relevant(owner, "预算 200 元") == []


def test_budget_is_reserved_before_mem0_extraction_and_search_failure_is_reported() -> None:
    client, service = FakeMem0(), None
    service = Mem0PreferenceService(client)
    with pytest.raises(Exception):
        service.apply(uuid.uuid4(), uuid.uuid4(), _action("remember"), RunBudget(BudgetLimits(model_requests=0)))
    assert client.add_calls == 0
    client.fail_search = True
    with pytest.raises(MemoryUnavailableError):
        service.relevant(uuid.uuid4(), "餐厅")
