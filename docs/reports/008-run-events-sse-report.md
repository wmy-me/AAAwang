# 008 持久化 Run 事件与 SSE 执行报告

## 结果

008 已完成。Run 状态转换现在与安全事件在同一数据库事务中提交；新增私有事件补读接口和独立 SSE 流，支持按 `sequence`/`Last-Event-ID` 断线续传。没有实现网页聊天、模型 token 流、LangGraph 或真实 Agent 业务执行。

## 实现

- 新增 `run_events` 表、`(run_id, sequence)` 唯一约束、增量索引和 `20261103_0005` 迁移。
- 创建、领取、取消、完成、失败、最大尝试次数租约回收均写入受控事件；重复取消、幂等创建和 fencing 拒绝不重复写事件。
- 新增 `GET /api/runs/{run_id}/events` 补读接口和 `GET /api/runs/{run_id}/events/stream` SSE 接口。鉴权与归属检查在流建立前完成。
- SSE 发送稳定事件 ID、事件类型和JSON payload；终态补发完成后关闭，客户端断开停止轮询。

## 自动验证

- 008 聚焦测试：`6 passed`。
- 覆盖事件顺序、取消幂等、用户隔离、SSE终态补发、游标读取和007 fencing回归。
- Ruff、compileall通过；未修改Java或网页工程。
- 全量Python回归：`41 passed`；`uv lock --check`、Ruff、compileall和编辑器诊断通过。
- 独立真实 PostgreSQL 17：从空库升级到 `20261103_0005`，重复升级无操作，`alembic check` 通过；真实 API 读取到 `run.queued`、`run.cancelled` 两个有序事件，重复取消没有新增事件。
- 真实 API 与两个独立 Worker 回归通过：幂等创建、单次领取、诊断完成、排队取消、租约接管和旧 Worker fencing 均通过。

## 未验证与边界

- 008新增事件的真实双Worker并发事件缺失检查未单独编写脚本；007回归已验证旧Worker fencing拒绝，自动测试覆盖迟到完成不改变终态事件。
- 流建立后的数据库故障以结束流处理，HTTP状态无法在响应开始后改为503；客户端按最后事件ID重连。
- 007之前已存在的Run不捏造历史事件；其当前状态仍由Run查询接口提供。
- 当前 `completed` 仍只表示无副作用诊断runner完成，不代表采购或出行方案完成。
- 临时数据库清理时发现用户ORM级联删除与 `runs.task_revision_id` 的 `RESTRICT` 约束存在删除顺序冲突；本轮未改变该既有数据删除语义。