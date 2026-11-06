# 030 对话短期上下文与统一执行预算报告

- 状态：已完成（浏览器交互未验证）
- 任务：[030](../vibe%20coding/030-conversation-context.md)
- 日期：2026-11-06

## 验收口径

本报告按任务文档中用户于 2026-11-06 确认的“验收范围修订”收口。该修订以已完成的真实主流程和有意义的自动化检查为准，替代旧矩阵及收口清单中要求重跑 Chrome 聊天、刷新、卡片、SSE、全量故障注入的更严格条目。未实际完成的浏览器交互仍逐项保留为未验证，不能误写成通过。

## 已实现并验证

- `ContextBuilder` 在查询中同时限定 conversation 与 owner，并以当前输入消息的 `(created_at, id)` 游标在数据库限制历史；游标不存在时 fail closed。稳定排序后，它仅返回有限近期 `user`/已完成 `assistant` 消息，失败或取消 Run 的 assistant 不进入视图。
- 历史按连续完整对话轮次的后缀裁剪；超长最新轮次不会被拆开，也不会跳过它而混入更早历史。默认上限为 `CONVERSATION_CONTEXT_MAX_MESSAGES=12` 和 `CONVERSATION_CONTEXT_MAX_CHARACTERS=12000`；字符限额是保守上限而非精确 token 计数，不自动摘要、不写长期记忆，也不改写原始消息。
- 路由、Worker 直答和 capability decision 使用各自所需的同一会话视图；当前明确输入和已确认 revision 条件仍来自各自可信持久化来源。
- `POST /conversations/{id}/turns` 仅在事务中写入用户消息及 taskless `conversation_route` Run；同一 `client_turn_id` 仍复用原 Run，API 不再执行模型路由。
- Worker 领取该 Run 后先在同一 `RunBudget` 内调用路由模型，再安全绑定为 `direct_answer` 或当前 owner/conversation 内的 shopping task/revision。网络调用不持事务行锁；取消与失租仍由检查和 fencing 阻止迟到终态写入。
- `RunBudget` 的每次 model、delegation、discovery 和 MCP 预占都以当前 claim 的 fencing token 立即写入 `runs.budget`；重领从快照恢复，损坏的非空快照安全终止而不静默重置，旧 Run 的空快照保持兼容。
- 没有迁移、敏感字段或新外部服务。

## 自动化检查

- 受控回归覆盖未来消息不进入旧回合、超长轮次和完整轮次裁剪、跨 owner 隔离、每类预算预占及恢复边界；`tests/test_budget.py tests/test_conversations.py tests/test_capability_worker.py` 为 `40 passed`。
- `cd backend && uv run pytest -q`：`181 passed`。
- `cd backend && uv run ruff check src tests`：通过。
- `cd backend && uv run python -m compileall -q src tests`：通过。
- `cd backend && uv run alembic check`：无待生成迁移（仅有既有 SQLAlchemy FK-cycle 警告）。
- `cd web && npm run lint && npm run build`：均通过；lint 输出 3 条既有 React Hooks 警告，未阻止命令或构建。

## 真实主流程验收（2026-11-06）

- 复用既有 PostgreSQL，启动独立 API、Worker、Java `shopping-mcp` 和 Vite，未启动备用 Compose。
- 真实 DeepSeek + API + 独立 Worker + PostgreSQL：新会话首句“只想要简短回答”与第二句“用它回答”均 completed；第二句回复保持简短偏好。两个 Run 各自记录 `model_requests=2`（路由+直答），REST 重读为 4 条消息，证明持久化回读。

## 浏览器和外部交互的事实边界

- Chromium 自动化实际完成了注册、登录和创建私有会话；页面发送控件并非脚本假设的 `textarea`，因此脚本没有实际发送任何消息。
- 本次没有真实 Chrome 消息、多轮回复、刷新或服务重启恢复、采买条件 revision、结果卡片、取消或 SSE 中断补读的证据。这些项目均为“未验证”，不是“通过”。
- 029 报告中已有的采买卡片、刷新与 SSE 历史证据仍属于 029，不替代本任务新的浏览器验收。

## 结论与保留限制

主流程已满足修订后的关闭标准：上下文按 owner/会话/游标隔离并完整轮次裁剪；路由移入持久化 Worker Run；路由、回答、委派、发现和 MCP 的预算预占均写入带 fencing 的 Run 快照；真实 DeepSeek—API—独立 Worker—PostgreSQL 两轮对话确认了跨回合短期上下文与每 Run 路由加回答的预算计数。因此 030 标记为“已完成（浏览器交互未验证）”。

本任务不实现长期偏好、RAG、自动摘要或 LangGraph checkpoint。外部调用状态不确定时不承诺 exactly-once。浏览器交互未验证范围如上；后续如需该范围应建立新的明确任务，不能把未执行的测试补写为本任务证据。
