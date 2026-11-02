# 私有对话 REST 契约

所有接口均位于 `/api`，使用 004 的 HttpOnly 登录 Cookie。未登录返回 `401`；数据库不可用返回不含连接细节的 `503`。对话不存在和不属于当前用户均返回相同的 `404`，不能据此枚举其他用户资源。

`POST`、`PATCH` 请求沿用受信 Origin 与 Fetch Metadata 检查。请求模型拒绝未声明字段，因此客户端不能提交 `owner_id`、`user_id`、`role` 或状态。正文只允许当前用户手工提交的纯文本，服务端固定消息角色为 `user`。

## 数据结构

对话包含 `id`、可空 `title`、`created_at` 和 `updated_at`。非空标题会去除首尾空白，长度为 1–120 个字符。

消息包含 `id`、`conversation_id`、`client_message_id`、固定值 `user` 的 `role`、`content` 和 `created_at`。`client_message_id` 长度为 1–128，正文长度为 1–8000；两者都不能只有空白。正文按客户端原文保存。服务端不生成 `assistant` 或 `tool` 消息。

## 接口

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| `POST /api/conversations` | `{"title": "可选标题"}` | `201` 与对话 |
| `GET /api/conversations?offset=0&limit=50` | 无 | `200` 与分页列表 |
| `GET /api/conversations/{id}` | 无 | `200` 与对话 |
| `PATCH /api/conversations/{id}` | `{"title": "新标题"}` | `200` 与更新后的对话 |
| `POST /api/conversations/{id}/messages` | `{"client_message_id": "...", "content": "..."}` | 首次 `201`；同文重试 `200` 与原消息 |
| `GET /api/conversations/{id}/messages?offset=0&limit=100` | 无 | `200` 与分页列表 |

分页响应为 `{"items": [...], "offset": 0, "limit": 50}`。`offset` 范围为 0–1,000,000，`limit` 范围为 1–100。对话按 `updated_at DESC, id DESC` 排序；消息按 `created_at ASC, id ASC` 排序，ID 在时间相同时提供确定顺序。

## 所有权与幂等

- 对话 owner 只取自服务端 `CurrentUser`，所有列表和单项查询均在数据库查询中限定 owner。
- `(conversation_id, client_message_id)` 在数据库中唯一。相同 ID 与相同正文重试返回原消息，不重复插入；相同 ID 与不同正文返回 `409`。
- 幂等查询在确认对话归属后执行。其他用户即使知道对话 ID 和客户端消息 ID，也只得到 `404`。
- 新增消息和更新对话 `updated_at` 在同一事务提交；失败不会返回伪造成功。

## 错误状态

| 状态 | 含义 |
| --- | --- |
| `401` | 缺少有效登录会话 |
| `403` | 跨站状态变更请求被拒绝 |
| `404` | 对话不存在或不属于当前用户 |
| `409` | 客户端消息 ID 已用于不同正文 |
| `422` | 字段、长度、UUID 或分页参数不合法，或包含额外字段 |
| `503` | 认证或对话存储暂时不可用 |