# 008：持久化 Run 事件与 SSE

- 状态：待执行；本文件仅是下一步执行任务，尚无实现或报告
- 所属阶段：P2 任务与对话基础
- 起始分支与代码提交：`main` / `98e00bf77038719bdb81708f8d82a88845dc9f03`；执行前核对最新 HEAD
- 前置：[007 持久化 Run 与最小 Worker](007-persistent-runs-worker.md)已有代码和[报告](../reports/007-persistent-runs-worker-report.md)
- 对应报告：`docs/reports/008-run-events-sse-report.md`
- 目标：为私有 run 保存可追溯状态事件，提供可按游标补读的 SSE；刷新、断线和 Worker 重启后不丢已提交事件，也不把诊断 runner 的完成误报为业务结果

## 1. 先读与确认

先读根 `CLAUDE.md`、[进度](../progress.md)、[路线图](../roadmap.md)、[任务索引](README.md)、[007 报告](../reports/007-persistent-runs-worker-report.md)、[run 契约](../../contracts/rest/runs.md)；核对 `backend/src/life_agent/modules/runs/service.py`、`worker/runner.py`、`api/routes/runs.py`、`db/models.py`、迁移与现有认证模式。查看 007 真实代码的事务边界和租约检查，再决定插入事件的位置。

007 只有 run 当前状态和诊断结果，没有历史事件、SSE 或补读接口。现在的 `completed` 只表示诊断执行成功；目前无模型 token 流、工具事件或方案事件。

## 2. 本轮范围

1. 新增 `run_events` 持久化表和迁移：事件稳定 ID（建议每 run 单调递增序号）、`run_id`、受控事件类型、时间、可安全返回的结构化 payload；建立 `(run_id, sequence)` 唯一约束和增量读取索引。事件写入与对应 run 状态转换同一数据库事务提交；失败回滚时不得留下虚假事件，成功状态不得缺少事件。预存的 007 run 不捏造历史事件，查询当前状态仍使用 `GET /api/runs/{id}`。
2. 从 007 的实际状态转换写入最小事件：`run.queued`、`run.running`、`run.cancel_requested`、`run.completed`、`run.failed`、`run.cancelled`；真实发生哪个转换才写哪个事件。取消重试或幂等创建不得产生重复事件；worker 被 fencing 拒绝的迟到完成不得产生终态事件。事件 payload 只含 `run_id`、状态、绑定 revision、时间和允许公开的诊断/错误摘要，不含 Cookie、密钥、完整条件快照或堆栈。
3. 新增私有 `GET /api/runs/{run_id}/events`：既支持普通分页/游标读取已提交事件，也提供独立 SSE 路径（例如 `GET /api/runs/{run_id}/events/stream`）。最终路径与字段固定在 `contracts/rest/run-events.md`，避免一个路径以不明确的 Accept 行为混用。两者使用与 007 相同的用户归属校验；不存在和越权都返回 404。
4. SSE 只从数据库中已提交事件递增发送，携带稳定 `id`、`event`、JSON `data`；支持 `Last-Event-ID` 或显式 `after` 游标重连，限定格式、长度和取值。先补发 `sequence > cursor` 的事件，再等待新事件，不在“查完历史”与“订阅新事件”之间漏掉提交。可以有界轮询数据库实现，无需本轮引入 Redis；控制轮询间隔、每轮批量上限、心跳和断连清理。
5. 匿名 401、越权 404 在开始流式响应前完成检查；建立连接时不把不存在的 run 先返回 200。会话失效、DB 暂不可用、客户端主动断开、run 到达终态后补发完毕等行为写入契约并验证。SSE 心跳是注释，不表示业务进度；终态可关闭流，重连仍可补读已存事件。

## 3. 实施顺序与可观察验收

1. 确定事件序列分配与事务方案，避免两个 Worker/取消请求同时写同一 run 时重复或乱序；新增模型、迁移、写入服务和 REST/SSE 契约。
2. 在 007 所有实际转换处接入事件；检查 `queued` 创建、取消、Worker 领取、完成、失败、租约过期接管的状态与事件一致。若发现已有状态转换竞态，做保证本任务验收所需的最小修复并在报告说明。
3. 聚焦测试：A/B 隔离和重连补发；重复幂等创建/取消不重复；同一游标不丢不重；旧 Worker 的 fencing 写入没有事件；已完成 run 和空事件 run；匿名、非法游标、跨站与数据库故障。事件测试验证真实状态效果，不只镜像序列化函数。
4. 用真实 PostgreSQL 启动 API 与两个独立 Worker；创建 run，观察 `queued → running → completed` 的保存/流式顺序；断开后凭最后事件 ID 重连只收后续事件；验证排队取消、旧租约接管以及跨用户 404。Python 回归、Ruff、编译、锁文件和 Alembic 检查通过；未动 Java/网页时不重复无关构建。

| 验收点 | 通过标准 |
| --- | --- |
| 事件与状态 | 真实提交一并保存，失败回滚两者都不出现；重试或重复操作不生成重复事件 |
| 私有性 | B 不能读取或订阅 A 的事件；匿名不能读；事件不含秘密字段 |
| 断线恢复 | 用保存的 event id 重连，已提交事件按序补齐，无遗漏和重复 |
| Worker 并发 | 两个 Worker 领取同一 run 仅一个成功；过期 Worker 的迟到写入不能生成事件 |
| SSE 生命周期 | 正确 content type、心跳、断连资源释放、终态关闭；数据库故障有定义行为 |

## 4. 完成与停止

实施后创建 `docs/reports/008-run-events-sse-report.md`，更新 `docs/progress.md`、[任务索引](README.md)、开发指南、run 与事件契约。报告区分自动测试、真实 PostgreSQL 联调与未验证项；满足关键验收才能标记完成。

本轮不做网页聊天界面、模型 token 流、LangGraph、意图识别、LLM/MCP Agent 执行或采买方案。008 完成后另拆网页对话与 Agent 接入；不能因 SSE 已联通就宣称用户能通过聊天获得业务答案。
