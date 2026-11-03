# 009 Run 删除链修复与事件真实并发回归报告

## 结果

009 已完成。`runs.task_revision_id` 的外键从 `RESTRICT` 改为 `CASCADE`，并新增 ORM 数据库级联配置；用户或任务真实删除时，其从属 Run 与事件一并清理，正常新增任务revision不会删除历史Run。

## 修复

- 新增迁移 `20261103_0006_run_revision_cascade`，不改写已发布的0004迁移；降级恢复 `RESTRICT`。
- `Run.task_revision_id` 与0006迁移一致使用 `ON DELETE CASCADE`。
- 用户、会话、对话、消息、任务、revision、Run和事件关系使用 `passive_deletes=True`，让数据库执行已声明的级联，避免ORM展开删除图造成顺序冲突。
- 新增 `scripts/check_deletion_events.py`，验证用户删除、Run/事件清理和跨用户保留。
- 扩展 `scripts/check_runs.py`，验证两个独立Worker的事件序列、租约接管、fencing无幽灵完成事件和SSE游标重连。

## 自动验证

- Python全量测试：`42 passed`。
- 删除链测试启用SQLite外键，验证删除Alice清理其Run/事件且Bob的Run保留。
- Ruff、compileall、`uv lock --check`和编辑器诊断通过。

## 真实PostgreSQL验收

- 在独立PostgreSQL 17中先升级到0005并创建存量数据：`1 run`、`2 events`。
- 从0005升级到0006后仍为`1 run`、`2 events`，Run与task revision关联为1；重复升级和`alembic check`通过，当前版本为0006 head。
- 两个独立Worker竞争同一Run：只产生一次`run.running`，正常序列为`queued → running → completed`。
- 模拟旧租约过期后新Worker接管：序列为`queued → running → running → completed`；旧fencing完成被拒，只有一个`run.completed`。
- 真实SSE使用`after=1`重连，只返回后续事件，没有重复或遗漏。
- 用户删除路径通过ORM删除已有完整关系；该用户的Run和事件清理成功，另一用户的Run保留。
- 另一个用户通过数据库父表直接 `DELETE` 删除；PostgreSQL级联清理其Run和事件，无孤儿数据，另一用户仍保留。
- 临时API、PostgreSQL容器和端口已清理。

## 边界

- 租约接管是数据库模拟过期，不是杀进程实验；报告不将其描述为实际进程崩溃恢复。
- 当前`completed`仍只表示无副作用诊断runner完成，不代表采购或出行方案完成。
- 本轮没有新增公开删除接口，也没有实现Agent、网页聊天或SSE token流。
