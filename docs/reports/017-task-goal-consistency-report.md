# 017 任务目标与结构化条件一致性报告

## 结论

017 的服务端一致性、网页冲突处理与 Run 前门禁已实现；真实浏览器已验证冲突展示、运行禁用、确认修订和刷新后的目标一致性。真实 DeepSeek/MCP 的新 Run 外部闭环未重新执行，017 验收表中的该项未满足，因此 017 标记为部分完成，不宣称本轮新增外部调用 exactly-once。

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

## 未完成与边界

- 已用现有隔离验收账号复现“目标预算 200、结构化预算 180”：任务卡显示冲突，Run 按钮禁用；确认后生成新 revision，目标与条件均为 180，刷新后仍保持一致。
- 手动 Run、聊天 turn 的服务端 409/无幽灵写入仍由自动测试覆盖；本轮未再次消耗真实模型/MCP预算。
- 因此 017 验收表“真实闭环”一行尚未全部满足，017 暂记部分完成；需用真实 Worker/DeepSeek/MCP 跑通一次冲突确认后的新 Run，才能整体收口。
- 外部 DeepSeek/MCP 调用不承诺 exactly-once。
