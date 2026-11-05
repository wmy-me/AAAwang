# 029 纯对话入口与 Agent 自主执行报告

- 状态：已完成
- 任务：[029 纯对话入口与 Agent 自主执行](../vibe%20coding/029-conversation-first-agent.md)
- 验证日期：2026-11-05
- 结论：纯对话入口、上下文任务/工具路由、taskless Worker Run、商品与来源卡历史关联/刷新/隔离、多任务歧义澄清及 DeepSeek HTTP 400 根因修复均已完成真实验收。

## 已实现

- 新增 `POST /conversations/{conversation_id}/turns`，已认证用户可以在没有 task 的新会话中提交自然语言回合。
- 新增模型级对话路由器：根据最近消息和当前任务列表判断 `chat/task/update_task/ambiguous`，不再用关键词预筛决定是否创建购物任务；模型不可用时才使用安全本地回退。
- 普通问候创建 taskless `direct_answer` Run，由 Worker 使用真实 DeepSeek 处理并持久化 assistant 消息；同一 `client_turn_id` 重试复用原 Run，重复请求返回 HTTP 200。
- 采买/工具请求由路由器创建或关联 shopping task 与 `capability_decision` Run；任务更新创建新 revision；多任务且没有明确指代时服务端强制澄清，不允许模型猜任务。
- 前端新建对话后直接展示全部会话消息和固定输入框；每条 assistant 消息按自身 `run_id` 加载商品/来源卡，历史消息不再被当前选中 Run 的卡片覆盖。旧任务列表仍可读取，但不是新会话发送的前置步骤。
- 已补充“25 个学生”等自然语言条件解析，保留预算、人数、数量和商品条件快照。
- 刷新会话时会恢复全部消息、各 Run 对应卡片、最新任务和服务端方案；无任务的普通会话仍保持纯对话视图。
- DeepSeek provider 的 HTTP 状态错误会保留安全的 `code/type/param/message` 诊断字段；已定位并修复 400 根因：纠正重试把带 `tool_calls` 的 assistant 消息直接回放，缺少对应 tool 消息。

## 自动化验证

- `cd backend && uv run ruff check src tests`：通过。
- `cd backend && uv run python -m compileall -q src tests`：通过。
- `cd backend && uv run pytest -q`：`175 passed`。
- `cd backend && uv run pytest -q tests/test_conversations.py`：`11 passed`。
- 新增覆盖模型分类替代关键词、任务显式关联、多任务拒绝猜测、400 纠正消息不带 tool_calls 回放。
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

## 本轮补充证据（2026-11-05）

1. 模型级路由：真实会话 `18d5092d-e6a3-41e8-b0d6-3cf45deba942` 中，问候创建 taskless Run `af964864-3a2b-47bc-b36f-5062527205cd`；采买消息创建 task `45ded7f9-1046-4bd3-9806-0f8c0342befc`，Run `57edd0eb-6130-4265-b5b0-5d8d8b6364e2` 完成并返回 2 个候选、有效方案。路由器不再用关键词直接决定是否创建任务。
2. 连续条件：同一会话“预算改为 180 元”创建 revision 2 和 Run `75c23959-0b17-4955-b2d1-ce48022bb325`，条件快照为预算 180；旧 Run 与旧条件仍可读。
3. 多任务歧义：新增第二个任务后发送“预算改为 150 元”，模型猜测了任务，但服务端要求多任务更新必须明确指代，最终创建 taskless Run `8cfdf8f5-82bb-4be3-a852-57ad43ddaf1a`，decision 为 `clarification`，未创建 revision 或改写任务。
4. 400 根因与修复：失败 Run `8cea21e1-...` 的 provider detail 显示“assistant message with tool_calls must be followed by tool messages”。修复 discovery 主 Agent 和 tool loop 的纠正重试，不再回放未执行的 `tool_calls`，而是回放纯文本 assistant 消息；同一采买场景复跑完成，未再出现 400。
5. 历史结果卡：真实商品 Run `57edd0eb...` 的 2 张商品卡与后续 Run 的消息并列显示；受控公开搜索 Run `771baae7-277d-4eb8-96e0-36121bd77a33` 提供 2 张来源卡，验证来源卡渲染、URL 和时间展示。浏览器刷新前后消息均为 10 条、卡片均为 4 张（2 商品 + 2 来源），无错误。
6. 隔离：第二账号读取上述会话消息、Run 和商品制品均为 404；浏览器登录第二账号时会话数、卡片数均为 0，页面不含第一账号会话。
7. 自动化：后端全量 `175 passed`，会话专项 `11 passed`；新增模型路由、显式任务关联、多任务拒绝猜测、纠正消息不回放 tool_calls 的回归测试。

## 边界

- 公开搜索来源卡使用受控 `WebSearchResult` 快照验证卡片历史/刷新/隔离；027 已单独完成真实 Tavily 协议、搜索 Run 和浏览器证据，本轮不在 029 重复消耗外部搜索配额。
- 对话路由器在 API 内同步调用一次模型进行分类，尚未计入 task-bound RunBudget；实际工具执行、Worker、取消和预算仍走既有共享预算路径。
- 未单独强制模拟 SSE 断线重连；浏览器刷新、消息重读和卡片恢复已验证，Run 终态与历史卡片仍从持久化 REST 快照恢复。
- 真实 Run 详情顶层 `artifacts` 仍为空，卡片使用受权限约束的独立结果接口；这是现有结果接口边界，不影响卡片刷新和隔离。
