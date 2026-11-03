# 017 任务目标与结构化条件一致性报告

## 结论

017 的服务端一致性、网页冲突处理与 Run 前门禁已实现；真实浏览器已验证冲突展示、运行禁用、确认修订和刷新后的目标一致性。补验又用真实 PostgreSQL、独立 Worker、DeepSeek 和 Java `shopping-mcp` 跑通了“冲突 409 → 确认修订 → 新 Run”的完整外部闭环：目标 200/条件 180 时手动 Run 和聊天 turn 均被拒绝且无幽灵写入，确认后 REV2 目标与条件均为 180，新 Run 用同一快照生成预算 ¥180 的方案。017 可以标记为完成；外部调用仍不承诺 exactly-once。

## 实现

- 新增 `TaskRevision.goal`、`goal_conflicts`、`goal_resolution`、`goal_legacy`，并新增 `Run.goal` 快照。
- 新增 0013 迁移：旧 revision 和 Run 回填当时可得的任务目标，并把旧 revision 标记为 legacy。
- 服务端检查购物目标中可明确识别的人数和预算；冲突包含字段、目标值、结构化值和原文片段。无法可靠识别的文本不推断为一致。
- 创建 Run 和任务聊天 turn 在事务内执行冲突门禁；冲突返回业务 409，且不创建 Run、Message，不调用模型或 MCP。
- Worker 从 `Run.goal` 与 `Run.conditions` 读取绑定快照，不再从可变 `Task.goal` 回读旧 Run 输入。
- 任务修订请求支持 `goal` 与 `confirm_goal_conflict`，确认时仅按结构化条件修正已识别冲突片段，并记录当前版本决议。
- 聊天回合响应改为使用 revision/Run 目标快照，避免返回可变任务投影。
- 网页任务卡支持目标编辑、服务端冲突展示、确认以结构化条件为准，并在冲突未解决时禁用 Run。
- 修复目标确认时重复追加预算单位的问题，确保“预算 180 元”不会变成“预算 180 元元”。

## 验证

- PostgreSQL 已真实升级至 0013，`alembic check` 通过。
- `uv run ruff check src migrations tests` 通过。
- `uv run python -m compileall -q src scripts tests` 通过。
- 017 实现前全量测试：`59 passed`；加入 017 测试后全量：`61 passed`。
- 前端 `npm run lint` 通过，仅保留既有 React hook 警告；`npm run build` 通过。

## 真实外部闭环补验

2026-11-03 在提交 `3f61900` 上用隔离账号 `accept016prizes` 新建对话与任务，未复用 016 任务；API 与独立 Worker 已用该提交代码重启。

| 检查 | 实际结果 |
| --- | --- |
| 冲突任务 | task `b4a18deb-4694-48e5-afe4-ae29572aa98e`，REV1 目标“总预算 200 元”，结构化条件 `budget=180`、`people=25`；接口返回 `goal_conflicts`：字段 budget、目标值 200、条件值 180、原文片段“总预算 200” |
| 手动 Run 门禁 | `POST /api/tasks/{task_id}/runs` 返回 409 与同一冲突；之后 Run 列表仍为 0 |
| 聊天 turn 门禁 | `POST /api/conversations/{conversation_id}/tasks/{task_id}/turns` 返回 409；消息列表与 Run 列表仍为 0 |
| 确认修订 | `confirm_goal_conflict=true` 生成 REV2，目标“总预算 180 元”，`goal_resolution=confirmed_structured_conditions`，无冲突 |
| 真实 Run | `ce9145dc-fa5d-45a4-a86d-0b6c91a5fcb5`，`completed`，`attempt=1`，08:48:45–08:48:55 UTC |
| 模型与 MCP | `model_requests=4`、`tool_calls=1`、`delegations=1`、`mcp_call_count=1`、`decision_type=delegated_discovery`、`simulated=true` |
| 候选与方案 | 2 个模拟候选；方案 REV2、预算 ¥180.00、合计 ¥6.90、余量 ¥173.10、覆盖 25/25 人、`unknown_fees=true` |
| 历史快照 | REV1 仍保留目标 200 元；REV2 目标 180 元；Run 绑定 REV2 的目标与条件 |
| 跨账号隔离 | 第二账号 `accept016probe` 读取任务、修订列表、Run、artifacts 和提交修订均返回 404 |

## 未完成与边界

- 真实浏览器的冲突展示、Run 禁用、确认和刷新一致性已在前次浏览器验收中记录；本节补验的是服务端、独立 Worker、真实 DeepSeek、Java `shopping-mcp` 和 PostgreSQL 的完整新 Run 链路。
- 本轮未单独压测“确认与并发修订”的竞态，仍依赖现有 revision 行级条件更新和 Run 事务门禁；自动测试覆盖 409 与无幽灵写入。
- 外部 DeepSeek/MCP 调用不承诺 exactly-once；金额仍是对模拟候选的服务端复算，不代表实时库存、报价或下单。
