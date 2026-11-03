from life_agent.modules.tasks.consistency import check_goal_consistency, resolve_goal


def test_goal_consistency_detects_budget_and_people_conflicts() -> None:
    result = check_goal_consistency(
        "为20名学生购买奖品，总预算200元",
        {"people": 25, "budget": 180, "quantity": 25},
    )

    assert {(item["field"], item["goal_value"], item["condition_value"]) for item in result.conflicts} == {
        ("people", 20, 25),
        ("budget", 200.0, 180),
    }


def test_goal_resolution_replaces_numbers_without_duplicate_units() -> None:
    goal = "教师为25名学生采购奖品，每人至少一份，总预算200元"
    conditions = {"people": 25, "budget": 180, "quantity": 25}
    consistency = check_goal_consistency(goal, conditions)

    assert resolve_goal(goal, conditions, consistency) == "教师为25名学生采购奖品，每人至少一份，总预算180元"
