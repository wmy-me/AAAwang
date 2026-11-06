"""Focused checks that general shopping guidance has no scene trigger."""

from life_agent.agents.discovery.graph import _supervisor_messages
from life_agent.agents.discovery.service import build_shopping_prompt
from life_agent.modules.intent.service import _validate


def test_different_procurement_examples_receive_the_same_general_guidance() -> None:
    teacher_prompt = _supervisor_messages("给学生买奖品", {"budget": 200})[0]["content"]
    cup_prompt = _supervisor_messages("推荐适合通勤的水杯", {})[0]["content"]
    assert "shopping_guidance" in teacher_prompt
    assert "shopping_guidance" in cup_prompt
    assert "teacher_rewards" not in teacher_prompt
    assert "teacher_rewards" not in cup_prompt


def test_missing_budget_supports_exploration_and_chat_does_not_select_tools() -> None:
    prompt = build_shopping_prompt("推荐适合通勤的水杯", {})
    assert "可先探索或追问" in prompt
    assert _validate({"intent": "chat", "task_id": None}, "你好", [])["intent"] == "chat"
