# 030 对话短期上下文与统一执行预算报告

- 状态：执行中，未验收完成
- 任务：[030](../vibe%20coding/030-conversation-context.md)
- 日期：2026-11-05

## 已实现并验证

- `ContextBuilder` 在查询中同时限定 conversation 与 owner，稳定排序后返回有限近期 `user`/已完成 `assistant` 消息；失败或取消 Run 的 assistant 不进入视图。
- 路由、Worker 直答和 capability decision 使用此视图；当前明确输入和已确认 revision 条件仍由各自可信持久化来源提供。
- 新增 `CONVERSATION_CONTEXT_MAX_MESSAGES=12` 与 `CONVERSATION_CONTEXT_MAX_CHARACTERS=12000`。字符限额是保守上限而非精确 token 计数；超限会标记历史不完整，不自动摘要、不写长期记忆，也不改写原始消息。
- 没有迁移、敏感字段或新外部服务。

### 0301：持久化路由与统一预算

- `POST /conversations/{id}/turns` 现在仅在事务中写入用户消息及 taskless `conversation_route` Run；同一 `client_turn_id` 仍复用原 Run。API 不再执行模型路由。
- Worker 领取该 Run 后，先用同一 `RunBudget` 调用路由模型；路由预占计数在绑定事务中写入 `runs.budget`，重领时从该快照恢复，避免已完成的路由调用绕过模型上限。网络调用完成后才短暂加锁，将 Run 安全改为 `direct_answer` 或绑定当前 owner/conversation 内的 shopping task/revision，再继续 capability decision、直答或只读工具调用。取消会在路由后、绑定前再次检查；失租时既有 fencing 阻止终态迟到写入。
- 新增替身路径覆盖“API 先返回 route Run、Worker 分类后才创建 task/revision”和“恢复已预占的路由模型预算”。定向命令现在为 `37 passed`。

### 本轮收口实现（2026-11-06）

- ContextBuilder 现在先按当前输入消息的 `(created_at, id)` 游标在数据库过滤，再裁剪历史；游标缺失时 fail closed。历史是连续完整轮次后缀，超长最新轮次不会被拆开或跳过以混入更旧信息。
- `RunBudget` 的每次 model、delegation、discovery 和 MCP 预占均通过当前 claim 的 fencing token 立即写入 `runs.budget`；重领从快照恢复，损坏的非空快照安全终止而不静默重置。网络调用期间不持锁。
- 受控回归新增未来消息、超长轮次、跨 owner、每类预占与恢复边界；`tests/test_budget.py tests/test_conversations.py tests/test_capability_worker.py` 为 `40 passed`，Ruff 通过。

## 真实验收（2026-11-06）

- 复用既有 PostgreSQL，Alembic check 无新增迁移并升级 head；启动独立 API、Worker、Java `shopping-mcp` 和 Vite（未启动 Compose）。
- 真实 DeepSeek + Worker + PostgreSQL：新会话首句“只想要简短回答”与第二句“用它回答”均 completed；第二句回复保持简短偏好。两个 Run 各自 budget 均记录 `model_requests=2`（路由+直答），消息刷新 REST 重读为 4 条。

`cd backend && uv run pytest -q tests/test_conversations.py tests/test_capability_worker.py tests/test_budget.py`：35 passed；Ruff 与 compileall 通过。新增测试覆盖顺序、截断点和跨 owner 拒绝。

## 未完成

完整 030 尚未完成：本轮未完成 Chrome 实操、服务重启后的浏览器恢复、采买条件修改/结果卡片和 SSE 中断补读，也未完成全量后端与前端构建矩阵。预算的跨重领恢复已有单元替身，仍需注入式失租/中断覆盖后续 discovery/MCP 分支。为避免误报，本任务保持执行中。
