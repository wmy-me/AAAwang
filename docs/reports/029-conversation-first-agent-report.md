# 029 纯对话入口与 Agent 自主执行报告

- 状态：执行中
- 任务：[029 纯对话入口与 Agent 自主执行](../vibe%20coding/029-conversation-first-agent.md)
- 验证日期：2026-11-05
- 结论：核心纯对话入口和购物自然语言自动建任务已接入并完成真实局部验收；完整 029 暂不标记完成。

## 已实现

- 新增 `POST /conversations/{conversation_id}/turns`，已认证用户可以在没有 task 的新会话中提交自然语言回合。
- 普通问候直接生成并持久化 assistant 消息，不创建 task 或 Run；同一 `client_turn_id` 重试复用原消息，重复请求返回 HTTP 200。
- 采买表达由服务端创建 shopping task、revision 1 和 `capability_decision` Run，并将用户消息绑定到该 Run；旧 task chat、Run、revision、SSE 和 API 保留兼容。
- 前端新建对话后直接展示会话消息区和固定输入框；旧任务列表仍可读取，但不是新会话发送的前置步骤。
- 已补充“25 个学生”等自然语言条件解析，保留预算、人数、数量和商品条件快照。

## 自动化验证

- `cd backend && uv run ruff check src tests`：通过。
- `cd backend && uv run python -m compileall -q src tests`：通过。
- `cd backend && uv run pytest -q`：`169 passed`。
- `cd backend && uv run pytest -q tests/test_conversations.py`：`6 passed`。
- `cd backend && uv run alembic check`：`No new upgrade operations detected`；保留既有 messages/runs 循环外键 warning。
- `cd web && npm run build`：通过。
- `cd web && npm run lint`：通过，保留 `App.tsx` 中 2 条既有 Hook warning。

## 真实验收证据

真实环境使用本地 PostgreSQL、真实 DeepSeek 配置、独立 Worker、Java `shopping-mcp` 和 Chromium：

1. 新建真实用户和会话后发送“你好，请用一句话介绍你能做什么。”，返回 assistant 文本；响应中的 `task` 和 `run` 均为 `null`。消息写入 PostgreSQL。
2. 同一会话发送“给 25 个学生买奖品，预算 200 元”，自动创建 task/revision/Run，条件为 `people=25`、`quantity=25`、`budget=200`、`item=奖品`。
3. 首次真实采买 Run 在 DeepSeek HTTP 400 后进入 `failed`，没有伪造 assistant 结果；这证明失败状态和错误摘要可持久化，但不作为闭环通过证据。
4. 使用“给学生买彩色铅笔，预算 200 元”重试，Run `7f1c1f15-75b4-443f-871b-4acc5c717d97` 最终 `completed`，选择 `shopping_product_discovery`，调用 `shopping-mcp`，assistant 消息持久化并明确标记模拟来源、候选、已知/未知项。
5. Chromium 真实操作新建对话、发送问候、刷新页面；刷新后用户和 assistant 消息仍可读，页面未要求创建任务或填写动态表单。

## 当前未满足项

- 普通对话仍在 API 请求内同步调用 DeepSeek，没有正式的 taskless Run；因此普通问答尚未复用独立 Worker、租约/fencing、SSE、取消和共享预算。
- 采买回合仍使用关键词初筛后进入既有 task-bound Run；会话级任务关联、歧义澄清和“预算改为 180 元”的新 revision 尚未完成完整真实验收。
- 前端尚未将商品候选和网页搜索快照渲染为会话内结果卡片；当前结果仍主要依赖既有 task/run 工作台路径。
- 尚未完成第二账号针对新会话级入口的真实浏览器越权验收，也未完成结果卡刷新/重连后的卡片恢复验收。
- 真实 DeepSeek 偶发 HTTP 400 的请求内容和重试策略还需继续定位；当前失败会安全终止，不会把失败写成成功结果。

因此 029 仍为执行中，下一步应先完成 taskless Run/SSE/Worker 设计，再补结果卡、连续对话 revision、双账号隔离和完整浏览器验收；本轮不开始 030。
