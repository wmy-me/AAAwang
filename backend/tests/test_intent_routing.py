"""Focused structural checks for the single intent-recognition boundary."""

from life_agent.modules.intent.service import _validate


def test_chat_and_existing_task_remain_separate_from_capability_choice() -> None:
    task_id = "11111111-1111-1111-1111-111111111111"
    assert _validate({"intent": "chat", "task_id": None}, "你好", [])["intent"] == "chat"
    routed = _validate(
        {"intent": "task", "task_id": task_id, "reason": "换一个商品"},
        "换一个看看",
        [{"id": task_id, "goal": "买铅笔"}],
    )
    assert routed["intent"] == "task"
    assert routed["task_id"] == task_id


def test_compound_request_is_clarified_instead_of_silently_dropping_one_intent() -> None:
    routed = _validate(
        {"intent": "memory", "memory_action": "remember", "secondary_intent": "task"},
        "记住不吃辣，再找一家餐厅",
        [],
    )
    assert routed["intent"] == "ambiguous"
    assert routed["task_id"] is None


def test_forget_needs_identity_but_not_a_new_value() -> None:
    routed = _validate(
        {"intent": "memory", "memory_action": "forget", "memory_category": "diet", "memory_key": "饮食偏好", "memory_value": None},
        "忘记我的饮食偏好",
        [],
    )
    assert routed["intent"] == "memory"
    assert routed["memory_action"] == "forget"
    assert routed["memory_value"] is None
    assert _validate({"intent": "memory", "memory_action": "forget"}, "忘记它", [])["intent"] == "ambiguous"
