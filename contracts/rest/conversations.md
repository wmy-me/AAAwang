# 私有对话 REST 契约

所有接口均位于 `/api`，使用 004 的 HttpOnly 登录 Cookie。未登录返回 `401`；数据库不可用返回不含连接细节的 `503`。对话不存在和不属于当前用户均返回相同的 `404`，不能据此枚举其他用户资源。

`POST`、`PATCH` 请求沿用受信 Origin 与 Fetch Metadata 检查。请求模型拒绝未声明字段，因此客户端不能提交 `owner_id`、`user_id`、`role` 或状态。手工消息与任务对话回合的正文只允许当前用户提交的纯文本；手工消息固定为 `user`，任务对话回合成功后由服务端另写一条 `assistant` 消息。

## 数据结构

对话包含 `id`、可空 `title`、`created_at` 和 `updated_at`。非空标题会去除首尾空白，长度为 1–120 个字符。

消息包含 `id`、`conversation_id`、`client_message_id`、`role`、`content`、可空 `task_id`、可空 `run_id` 和 `created_at`。`client_message_id` 长度为 1–128，正文长度为 1–8000；两者都不能只有空白。任务对话产生的用户消息和 assistant 消息都绑定同一 `task_id`/`run_id`；每个 Run 至多一条 assistant 消息。服务端只允许在 Run completed 且结果持久化时写入 assistant 消息。

## 接口

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| `POST /api/conversations` | `{"title": "可选标题"}` | `201` 与对话 |
| `GET /api/conversations?offset=0&limit=50` | 无 | `200` 与分页列表 |
| `GET /api/conversations/{id}` | 无 | `200` 与对话 |
| `PATCH /api/conversations/{id}` | `{"title": "新标题"}` | `200` 与更新后的对话 |
| `POST /api/conversations/{id}/messages` | `{"client_message_id": "...", "content": "..."}` | 首次 `201`；同文重试 `200` 与原消息 |
| `POST /api/conversations/{id}/tasks/{task_id}/turns` | `{"client_turn_id": "...", "content": "...", "task_id": "...", "expected_revision": 1}` | 首次 `201`；同键同请求重试 `200` 与原消息/Run/assistant |
| `GET /api/conversations/{id}/messages?offset=0&limit=100` | 无 | `200` 与分页列表 |

分页响应为 `{"items": [...], "offset": 0, "limit": 50}`。`offset` 范围为 0–1,000,000，`limit` 范围为 1–100。对话按 `updated_at DESC, id DESC` 排序；消息按 `created_at ASC, id ASC` 排序，ID 在时间相同时提供确定顺序。

## 所有权与幂等

- 对话 owner 只取自服务端 `CurrentUser`，所有列表和单项查询均在数据库查询中限定 owner。
- `(conversation_id, client_message_id)` 在数据库中唯一。相同 ID 与相同正文重试返回原消息，不重复插入；相同 ID 与不同正文返回 `409`。
- 幂等查询在确认对话归属后执行。其他用户即使知道对话 ID 和客户端消息 ID，也只得到 `404`。
- 新增消息和更新对话 `updated_at` 在同一事务提交；失败不会返回伪造成功。
- 任务对话回合只允许当前用户、当前对话下的 shopping task；任务不存在、跨账号、跨对话或非购物任务统一 `404`。
- 回合使用 `client_turn_id` 作为幂等键：同一对话、同一用户、同一内容、同一 task 和预期版本的重试返回原消息与原 Run；同键不同请求返回 `409`。`expected_revision` 与当前版本不符返回 `409`。
- 回合在同一事务内按需创建新的 TaskRevision、写入用户消息并创建 `shopping_agent` Run；用户消息与 Run 互相绑定。条件只根据用户明确补充的 `budget`/`people`/`quantity`/`item` 合并，未提及字段沿用原快照。
- completed Run 至多写入一条绑定该 Run 的 assistant 消息，正文与 Run 结果一致；failed/cancelled Run 不写 assistant 消息。

## 错误状态

| 状态 | 含义 |
| --- | --- |
| `401` | 缺少有效登录会话 |
| `403` | 跨站状态变更请求被拒绝 |
| `404` | 对话不存在或不属于当前用户 |
| `409` | 客户端消息 ID/回合键已用于不同请求，或 `expected_revision` 已过期 |
| `422` | 字段、长度、UUID 或分页参数不合法，或包含额外字段 |
| `503` | 认证或对话存储暂时不可用 |