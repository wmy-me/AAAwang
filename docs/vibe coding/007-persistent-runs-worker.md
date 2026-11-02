# 007：持久化 Run 与最小 Worker

- 状态：待执行；本文件是下一步执行任务，不表示已有实现
- 所属阶段：P2 任务与对话基础
- 起始分支与代码提交：`main` / `56be3b6c044fa57a431f1fb3c8aa1f4697aa5cb4`；实施前再次核对 HEAD 并保留之后的改动
- 前置：[006 私有任务与条件版本](006-task-revisions.md)已提交；[执行报告](../reports/006-task-revisions-report.md)记录真实 PostgreSQL 验证
- 对应报告：`docs/reports/007-persistent-runs-worker-report.md`
- 目标：用户能为自己任务的**明确条件版本**创建一个持久化 run；独立 Worker 安全领取、记录终态，并在请求重试、进程崩溃和任务条件修改后仍能解释该 run 执行的版本

## 1. 先读与现状

先读根 `CLAUDE.md`、[当前进度](../progress.md)、[路线图](../roadmap.md)、[任务索引](README.md)、[006 报告](../reports/006-task-revisions-report.md)、[任务 REST 契约](../../contracts/rest/tasks.md)；核对 `backend/src/life_agent/db/models.py`、`modules/tasks/`、`api/dependencies.py`、`db/session.py`、`worker/`、Alembic 和测试模式。不要把任务条件版本或对话消息当作可恢复的运行记录。

006 只有 task/revision：没有 run、队列、Worker、状态、取消或执行结果。现有 003 是独立命令行工具循环，不能作为已持久化的 Agent run。

## 2. 本轮范围

1. 用 Alembic 新建持久化 `runs` 表。每个 run 绑定 `task_id`、创建时的 `task_revision_id` / 版本号及该版本的完整条件快照（至少可从不可变 revision 读取），保存 owner 可追溯关系、创建时间、开始/结束时间、状态、有限的执行诊断与错误摘要。若现有 revision 无数据库层不可变保障，至少禁止业务写路径修改；run 绝不能读取后来变化的 current revision 作为本次执行参数。
2. 增加私有 REST：`POST /api/tasks/{task_id}/runs`（显式 `expected_revision` 和客户端幂等键）、`GET /api/tasks/{task_id}/runs`（分页）、`GET /api/runs/{run_id}`、`POST /api/runs/{run_id}/cancel`。身份只从 `CurrentUser`；越权与不存在统一 404；过期版本 409；重复键同请求返回同一 run，异请求冲突 409；写入沿用可信 Origin 限制。响应应给出绑定版本、状态与时间，不能声称已有采购/出行方案。
3. 用独立进程入口运行最小 Worker（与 API 共用 Python 工程和 PostgreSQL）。多个 Worker 用数据库原子领取（如 `FOR UPDATE SKIP LOCKED`）保证同一 run 不被并发执行；领取带 `worker_id`、租约截止时间与 fencing/attempt 标识，完成更新须验证持有权。Worker 不能把进程内后台任务或 HTTP 请求生命周期当队列。
4. 本轮的 runner 只做可重复、只读、可控的基础设施诊断：记录所领取的 task/revision、启动/结束信息和明确的“尚未运行 Agent 规划”结果。它不调用 LLM、MCP、交易或消息写入，不生成假方案。可用短时间延迟的测试替身验证取消、重领与所有权；正式运行无外部副作用。一个任务可有多个 run，状态互不串扰。
5. 定义 `queued → running → completed/failed/cancelled` 的允许转换；`queued` 可取消，`running` 为协作式取消，在 Worker 检查点或租约回收后落为 cancelled；领取后进程崩溃由租约到期回收，设置有限重试/最终失败策略。过期 Worker 的写入不能覆盖新持有者的结果。部署、启动、优雅关闭、轮询和退避配置写进开发指南。

## 3. 契约与异常语义

先在 `contracts/rest/runs.md` 固定字段、幂等键作用域（建议每 task 唯一）、状态、分页、取消重复请求语义、租约/重试和故障返回，再实现。任务更新后，新 run 使用新版本；旧 run 保持旧版本。API 创建 run 时要用事务保护 `expected_revision` 与绑定快照，避免并发修订导致一份 run 指向另一份条件。

取消不是强杀线程或保证立即终止外部调用；本轮 runner 无副作用，但后续 Agent 接入仍需在每个工具调用前验证取消和租约。数据库不可用返回安全 503；不要把 Worker 内部堆栈、密钥或数据库 URL 暴露给客户端。不得依赖前端轮询来保证最终落库。

## 4. 实施与验收

1. 核对 006 的迁移、schema、身份依赖与真实 PostgreSQL 配置；确定状态机和事务边界；实现迁移、service、REST 契约、Worker 入口及开发说明。
2. 聚焦测试：同一任务两个 run 独立；同一幂等键重试；两个用户互访 404；过期 `expected_revision` 409；改条件后旧 run 仍指向旧 revision；非法输入和断库；取消排队任务/运行任务；双 Worker 同时领取至多一个成功；租约过期后旧 Worker 的迟到完成被拒绝。
3. 用真实 PostgreSQL 17 从 006 head 升级并检查迁移；启动 API + 两个独立 Worker 进程，走创建、幂等重试、领取完成、取消、进程中断及租约回收链路。替身或 SQLite 测试只能作快速反馈，不能代替并发/租约验收。只对可控无副作用 runner 做重试，不重复调用外部服务。
4. 运行已有 Python 回归、Ruff、编译、锁文件与 Alembic 检查；未修改 Java/网页时无需重复无关构建。报告实际命令、环境、结果和未验证项。

| 验收点 | 可观察结果 |
| --- | --- |
| 持久化与隔离 | A 的 run 可由新客户端重读；B 所有创建、读取、列表、取消路径均不能访问 A 的 run |
| 版本与幂等 | 指定版本绑定正确，过期版本拒绝，重复请求返回同一 run，修改条件不影响旧 run |
| Worker 所有权 | 双 Worker 仅一个取得执行权；崩溃可回收；租约过期的旧 Worker 无法写入终态 |
| 取消与故障 | 排队及运行中取消语义明确并最终落库；断库不误报成功；失败次数有上限 |

## 5. 完成后停止

建立 `docs/reports/007-persistent-runs-worker-report.md`，更新 `docs/progress.md`、[任务索引](README.md)、REST 契约和开发指南。只有真实 PostgreSQL 的关键验收通过才标记完成，否则注明部分完成或阻塞。

本轮不做 SSE、网页对话、LangGraph、意图识别、LLM/MCP 集成、业务方案或 Java 服务扩展。下一步再拆事件与 SSE、网页界面和 Agent 真正执行；run 的 `completed` 仅代表本轮诊断 runner 完成。
