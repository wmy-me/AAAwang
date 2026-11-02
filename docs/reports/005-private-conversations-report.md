# 005 私有对话与消息持久化报告

**项目：** 生活采买智能体  
**阶段：** P2 任务与对话基础  
**执行日期：** 2026-11-02  
**任务文档基线：** `454fe132630d921e1d5b5cdd9d380344f2e991d3`  
**实际执行起点：** `75f62f3c233a19b53a023e0f7a38eba5ffaf38c8`  
**结论：** 已完成。私有对话与手工用户消息已持久化，并通过真实 PostgreSQL 双用户隔离和幂等验收。

## 1. 实现

Alembic `20261102_0002` 新增：

- `conversations`：UUID、owner 外键、可空标题、创建/更新时间；用户删除时级联删除。
- `messages`：UUID、conversation 外键、客户端消息 ID、固定 `user` 角色、纯文本正文和创建时间；对话删除时级联删除。
- `(conversation_id, client_message_id)` 唯一约束用于并发幂等兜底。
- 对话按 owner、更新时间和 ID 建复合索引；消息按 conversation、创建时间和 ID 建复合索引，时间相同时仍有确定顺序。

新增六个接口：

- `POST /api/conversations`
- `GET /api/conversations`
- `GET /api/conversations/{id}`
- `PATCH /api/conversations/{id}`
- `POST /api/conversations/{id}/messages`
- `GET /api/conversations/{id}/messages`

所有权只来自 004 的 `CurrentUser`。服务层查询直接同时限定资源 ID 和 owner ID；不存在与越权统一 404。请求模型拒绝 `owner_id`、`user_id`、`role` 等额外字段，写请求复用已有 Origin 与 Fetch Metadata 检查。

消息客户端 ID 长度为 1–128，正文为 1–8000，标题为 1–120；空白输入和分页范围均有验证。同 ID、同正文重试返回原消息和 200；同 ID、不同正文返回 409。新增消息与对话更新时间在一个事务提交。

## 2. 自动测试

SQLite StaticPool 仅作为快速接口边界替身，不作为最终持久化证据。新增 4 项聚焦测试覆盖：

- A、B 双向列表、读取、改标题、追加消息和消息读取隔离。
- 创建、更新、稳定消息顺序及新 TestClient 携带 Cookie 恢复读取。
- 同文幂等只保留一行、异文 409 且错误响应不回显私有正文。
- 匿名 401、伪造 owner/user/role 422、空白与分页边界 422、跨站写入 403。

最终执行 `uv lock --check`、Ruff、compileall 和全量 pytest，结果为 **31 passed**，包含 001–004 回归。VS Code 测试适配器未发现 uv 子工程测试，实际结果来自锁定环境中的 `uv run pytest`。

## 3. 真实 PostgreSQL 17

使用独立临时容器、宿主端口 55433 和空数据库验收，不占用默认 5432：

1. 从空库升级 `0001 -> 0002` 成功，重复 `upgrade head` 无操作。
2. `alembic current` 为 `20261102_0002 (head)`，`alembic check` 无模型漂移。
3. 单独降级到 `20261102_0001` 后可重新升级到 head。
4. 004 的 `check_auth.py` 继续通过。
5. A、B 各创建私有对话；B 对 A 的四类访问均为 404，A 读取 B 也为 404，B 列表不出现 A 数据。
6. 关闭首个 TestClient 后，新客户端携带 A 的 Cookie 可读取 A 的持久化消息。
7. 同文重试返回同一消息 ID；异文返回 409；数据库实际为 2 个对话、1 条消息。
8. 停止 PostgreSQL 后，`/api/health` 为 200，带有效 Cookie 的对话请求为安全 503，响应不含连接信息。

验收后已停止临时 Uvicorn，删除临时容器与 HTTP 临时文件。未修改 Java 或网页源码，因此未重复其构建。

## 4. 边界

- 本轮只保存用户手工纯文本；没有调用模型或 MCP，没有助手/tool 消息、流式响应或 Agent 长期记忆。
- 没有 task、run、方案、任务条件版本、Worker、取消或 SSE；P2 尚未整体完成。
- 网页没有登录或对话界面，本轮未新增或重复验证 Vite 对话代理流程。
- 数据库唯一约束和异常后重读覆盖并发竞争语义，但未执行高并发压力测试。
- 分页使用有确定次序的 offset/limit；超大且频繁变动的数据集未来可按实际需求升级为游标分页。