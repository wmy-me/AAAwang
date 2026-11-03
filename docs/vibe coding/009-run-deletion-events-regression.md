# 009：Run 删除链修复与事件真实并发回归

- 状态：已完成；实现与验收见[报告](../reports/009-run-deletion-events-regression-report.md)
- 所属阶段：P2 任务与对话基础（数据生命周期与事件验收收尾）
- 起始分支与代码提交：`main` / `d2c28f16453b5b832f466f6ff03e5ca0e0401ce0`；实施前核对最新 HEAD
- 前置：[007 Run 与 Worker](007-persistent-runs-worker.md)、[008 事件与 SSE](008-run-events-sse.md)已提交；阅读 [008 报告](../reports/008-run-events-sse-report.md)中的未验证项
- 对应报告：`docs/reports/009-run-deletion-events-regression-report.md`
- 目标：在真实 PostgreSQL 上修复删除用户/任务数据时的 run—revision 外键顺序冲突，并补齐 008 尚缺的多 Worker 状态事件与断线恢复验收

## 1. 问题与先读

008 报告记录：临时库清理时，ORM 级联删除用户与 `runs.task_revision_id → task_revisions.id ON DELETE RESTRICT` 冲突。这个问题在已有 run 的账户数据生命周期中可复现风险；007/008 的一般运行验证不能证明删除链安全。008 已执行真实 PostgreSQL 升级、API 的 queued/cancelled 事件和双 Worker 基础回归，但**没有独立验证双 Worker 竞争、租约接管时每个事件的完整顺序和 fencing 后无幽灵事件**。

先读根 `CLAUDE.md`、[当前进度](../progress.md)、[任务索引](README.md)、[008 报告](../reports/008-run-events-sse-report.md)、[run 契约](../../contracts/rest/runs.md)、[事件契约](../../contracts/rest/run-events.md)；核对 `backend/src/life_agent/db/models.py`、0003–0005 迁移、`modules/runs/service.py`、`worker/runner.py`、现有测试与清理脚本。先在隔离真实库中复现，再决定最小迁移与 ORM 关系调整。

## 2. 修复范围

1. 明确现有用户、对话、任务、revision、run、事件的删除语义：正常修订只新增 revision，绝不误删旧 run；仅当所属用户/任务真的删除时清理其从属 run 与事件。现阶段不新增公开删除接口，不借本任务扩张用户功能。
2. 新增 Alembic 迁移修正 `runs.task_revision_id` 外键与 ORM 级联顺序。选择能同时保证引用有效和上级删除可完成的方案（如 `ON DELETE CASCADE` 配合一致的 ORM 关系），先检查已有行和历史迁移兼容性；**不改写已发布的 0004 迁移**。有数据升级时不可丢失正常 run；降级应有明确行为。
3. 用真实 PostgreSQL 验证两种实际删除路径：通过 ORM 删除已有完整关系的 User、Conversation 或 Task（按目前受支持路径）；通过数据库父表删除触发级联。结束后检查关联的 run/revision/event 均无孤儿，另一用户数据仍在。若某路径不在本项目支持范围，契约与报告明确说明，避免声称都已通过。
4. 补齐真实 API、PostgreSQL 和**两个独立 Worker 进程**的 008 事件验收：相同 run 原子领取只记录一次成功的 running，正常完成只有一个终态事件；模拟旧租约过期后新 Worker 接管，旧 fencing 完成被拒且不能产生完成事件；SSE/补读按最后 sequence 断线重连，无丢失或重复。进程中断如未真正杀进程，报告准确写成“数据库模拟租约过期”。
5. 与改动相关的快速测试覆盖 ORM 删除链和事件并发语义；事件写入仍与 run 状态事务一致，不在非终态误报采购或出行结果。保留 A/B 用户隔离、Cookie 会话和错误响应边界。

## 3. 验收与完成

| 场景 | 通过标准 |
| --- | --- |
| 现有数据迁移 | 从真实 0005 数据库升级，原有 run/revision/event 数量与关联可读；重复升级、`alembic check` 通过 |
| 数据删除 | 含历史版本、多个 run 与事件的用户/任务能按约定删除；无外键错误、无跨用户误删、无孤儿 |
| 双 Worker 事件 | 竞争、接管及旧 Worker 迟到场景的事件序列与 run 最终状态一致；重连仅返回游标之后的事件 |
| 回归 | Python 现有测试、Ruff、编译、锁检查通过；真实 PostgreSQL 验证与替身结果分别记录 |

实施后更新迁移/模型、相关测试及开发说明，在 `docs/reports/009-run-deletion-events-regression-report.md` 记录复现、修复方案、实际 SQL/命令、真实数据库结果和剩余风险；同步 [进度](../progress.md)、[任务索引](README.md)、受影响契约。关键真实库验收没通过时标记部分完成或受阻。

完成后停止。后续优先把现有 DeepSeek/MCP 有限工具循环接入持久化 run，再做网页对话；本轮不实现 Agent、商品规划、SSE token 流或新业务接口。
