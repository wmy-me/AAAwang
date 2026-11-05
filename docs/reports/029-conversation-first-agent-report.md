# 029 纯对话入口与 Agent 自主执行报告

- 状态：执行中
- 任务：[029 纯对话入口与 Agent 自主执行](../vibe%20coding/029-conversation-first-agent.md)
- 验证日期：2026-11-05
- 结论：核心纯对话入口和购物自然语言自动建任务已接入并完成真实局部验收；完整 029 暂不标记完成。

## 已实现

- 新增 `POST /conversations/{conversation_id}/turns`，已认证用户可以在没有 task 的新会话中提交自然语言回合。
- 普通问候创建 taskless `direct_answer` Run，由 Worker 使用真实 DeepSeek 处理并持久化 assistant 消息；同一 `client_turn_id` 重试复用原 Run，重复请求返回 HTTP 200。
- 采买表达由服务端创建 shopping task、revision 1 和 `capability_decision` Run，并将用户消息绑定到该 Run；旧 task chat、Run、revision、SSE 和 API 保留兼容。
- 前端新建对话后直接展示会话消息区和固定输入框；旧任务列表仍可读取，但不是新会话发送的前置步骤。
- 已补充“25 个学生”等自然语言条件解析，保留预算、人数、数量和商品条件快照。
- 刷新会话时会恢复最新任务、Run、assistant 消息、商品候选卡和服务端校验方案；无任务的普通会话仍保持纯对话视图。
- DeepSeek provider 的 HTTP 状态错误会保留安全的 `code/type/param/message` 诊断字段，不记录 API key、完整提示词或敏感响应。

## 自动化验证

- `cd backend && uv run ruff check src tests`：通过。
- `cd backend && uv run python -m compileall -q src tests`：通过。
- `cd backend && uv run pytest -q`：`170 passed`。
- `cd backend && uv run pytest -q tests/test_conversations.py`：`7 passed`。
- `cd backend && uv run alembic check`：`No new upgrade operations detected`；保留既有 messages/runs 循环外键 warning。
- `cd web && npm run build`：通过。
- `cd web && npm run lint`：通过，保留 `App.tsx` 中 2 条既有 Hook warning。

## 真实验收证据

真实环境使用本地 PostgreSQL、真实 DeepSeek 配置、独立 Worker、Java `shopping-mcp` 和 Chromium：

1. 新建真实用户和会话后发送“你好，请用一句话介绍你能做什么。”，创建 taskless Run `726b882d-18f5-4d4d-80a0-ed113f7d85f4` 并完成；`task_id`、`task_revision_id` 均为 `null`，真实 Worker 使用 1 次模型请求，assistant 消息写入 PostgreSQL。
2. 同一会话发送“给 25 个学生买奖品，预算 200 元”，自动创建 task/revision/Run，条件为 `people=25`、`quantity=25`、`budget=200`、`item=奖品`。
3. 首次真实采买 Run 在 DeepSeek HTTP 400 后进入 `failed`，没有伪造 assistant 结果；这证明失败状态和错误摘要可持久化，但不作为闭环通过证据。
4. 使用“给学生买彩色铅笔，预算 200 元”，真实 Run `4d49ef26-293a-4fad-b841-03f9785b750d` 最终 `completed`，调用 `shopping-mcp`，assistant 消息持久化并明确标记模拟来源、候选、已知/未知项。
5. 同一真实会话发送“预算改为 180 元”，创建 revision 2 和 Run `c7c4f6f4-0d99-4fcb-9a2d-ec215ba4d273`；Run 最终 `completed`，预算快照为 180，assistant 消息持久化。此前暴露的 500 根因是 revision 目标仍保留旧预算文本，已由已确认的目标冲突解析修复。
6. Chromium 真实操作新建对话、发送问候、刷新页面；刷新后用户和 assistant 消息仍可读，页面未要求创建任务或填写动态表单。
7. Chromium 真实发送“给学生买彩色铅笔，预算 200 元”，Run 完成后聊天区显示商品结果卡；刷新页面后 task、Run、候选卡和校验方案均恢复。
8. Chromium 真实发送原始表达“给 25 个学生买奖品，预算 200 元”，Run `9e01790b-1438-418c-b802-14bce0bb7680` 完成，真实方案覆盖 `25/25` 人，结果卡显示 2 个模拟候选；未复现此前 HTTP 400。
9. 第二真实账号读取第一账号会话消息返回 HTTP 404；taskless Run 立即取消后终态为 `cancelled`，未写入 assistant 结果。

## 当前未满足项

- taskless Run 已复用 Worker、租约/fencing、取消检查和共享预算代码；浏览器 SSE 连接在 Run 终态切换时会主动关闭，独立的断线重连专门验收仍需补充。
- 采买回合仍使用关键词初筛后进入既有 task-bound Run；模型级歧义澄清尚未替代关键词初筛，这是 029 当前剩余的架构缺口。
- 真实 Run 详情的顶层 `artifacts` 仍为空；结果卡使用独立的 `/shopping-artifacts`、`/web-search-results` 受权限约束接口，已完成真实浏览器显示和刷新恢复验证。
- 尚未完成第二账号针对新会话级入口的真实浏览器越权验收，也未完成结果卡刷新/重连后的卡片恢复验收。
- 真实 DeepSeek 偶发 HTTP 400 的请求内容和重试策略还需继续定位；当前失败会安全终止，不会把失败写成成功结果。

因此 029 仍为执行中，下一步应先完成 taskless Run/SSE/Worker 设计，再补结果卡、连续对话 revision、双账号隔离和完整浏览器验收；本轮不开始 030。
