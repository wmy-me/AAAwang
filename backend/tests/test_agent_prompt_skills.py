"""Prompt asset and scene Skill boundaries for task 024."""

import pytest

from life_agent.agents.discovery.nodes import delegate_tool
from life_agent.agents.shared.prompt_loader import PromptAssetError, load_prompt
from life_agent.agents.shared.skill_loader import (
    SkillDefinition,
    register_skill,
    select_skill,
    skill_context,
)


def test_trusted_role_prompts_load_from_separate_assets() -> None:
    discovery = load_prompt("../discovery/prompts/system.md")
    coordinator = load_prompt("../coordinator/prompts/system.md")
    assert "商品信息发现 Agent" in discovery
    assert "主协调 Agent" in coordinator
    assert discovery != coordinator


def test_missing_prompt_asset_fails_with_diagnostic_error() -> None:
    with pytest.raises(PromptAssetError, match="提示资产"):
        load_prompt("../discovery/prompts/missing.md")


def test_teacher_skill_is_selected_only_for_matching_scene() -> None:
    teacher = select_skill("给学生买奖品")
    assert teacher is not None
    assert teacher.name == "teacher_rewards"
    assert "奖品" in skill_context("给学生买奖品")
    assert select_skill("买普通水杯") is None
    assert select_skill("查询上海天气") is None
    assert select_skill("你好") is None


def test_registered_skill_extends_registry_without_graph_change() -> None:
    register_skill(
        SkillDefinition(
            name="test_stationery",
            version="1.0",
            scope="文具",
            triggers=("文具测试场景",),
            guidance="只提供测试参考。",
            source="test",
        )
    )
    selected = select_skill("文具测试场景", allowed_names=("test_stationery",))
    assert selected is not None
    assert selected.name == "test_stationery"
    assert "只提供测试参考" in skill_context("文具测试场景", allowed_names=("test_stationery",))


def test_skill_text_does_not_change_authorized_delegate_tool() -> None:
    tool = delegate_tool()
    assert tool["function"]["name"] == "delegate_shopping_discovery"
    assert "url" not in tool["function"]["parameters"]["properties"]
