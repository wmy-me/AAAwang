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

`cd backend && uv run pytest -q tests/test_conversations.py tests/test_capability_worker.py tests/test_budget.py`：35 passed；Ruff 与 compileall 通过。新增测试覆盖顺序、截断点和跨 owner 拒绝。

## 未完成

路由已进入 Worker 和同一内存 `RunBudget`，但完整 030 尚未完成：仍需补充持久预算跨重领/重试不重置的替身证明、路由+回答/委派的上限/超时/失租专项，以及真实 DeepSeek、PostgreSQL、Chrome、SSE 验收。为避免误报，本任务保持执行中。
