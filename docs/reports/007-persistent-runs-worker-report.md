# 007 持久化 Run 与最小 Worker 报告

**项目：** 生活采买智能体  
**阶段：** P2 任务与对话基础  
**执行日期：** 2026-11-03  
**实际执行起点：** `94450018eb881e1317b6d651d212331cdd8535b7`  
**结论：** 已完成。本轮 run、版本绑定、幂等、取消和独立 Worker 租约恢复已通过自动测试与真实 PostgreSQL 17 验收。

## 1. 实现内容

- Alembic `20261103_0004` 新增 `runs` 表。run 保存 owner、task、不可变 `task_revision_id`、revision、完整 conditions 快照、状态、时间、attempt、租约、fencing token、有限诊断和错误摘要。
- 新增 `POST /api/tasks/{task_id}/runs`、`GET /api/tasks/{task_id}/runs`、`GET /api/runs/{run_id}` 和 `POST /api/runs/{run_id}/cancel`。创建事务锁定 task 并核对 `expected_revision`；task 内幂等键由数据库唯一约束兜底。
- 新增独立 `python -m life_agent.worker.runner` 入口。数据库 `FOR UPDATE SKIP LOCKED` 领取 queued 或过期可重试 run，终态更新验证 worker、fencing token 和租约；最多 3 次尝试，过期后失败。
- 当前 runner 只记录 task/revision 和“尚未运行 Agent 规划”的只读诊断，不调用 LLM、MCP、交易或消息写入。

## 2. 快速验证

命令：

```bash
cd backend
uv run ruff check src scripts tests migrations
uv run python -m compileall -q src scripts tests migrations
uv run pytest -q
```

结果：Ruff 和 compileall 通过，Python 全量 **39 passed**。其中 `tests/test_runs.py` 的 4 项测试覆盖版本快照、幂等、隔离、取消和 fencing。

## 3. 真实 PostgreSQL 17 验收

使用临时 `postgres:17` 容器和宿主端口 `55437`，数据库从空库升级：

- `alembic upgrade head` 从 0001 连续升级到 `20261103_0004`，重复升级无操作。
- `alembic current` 为 `20261103_0004 (head)`，`alembic check` 报告无新升级操作。
- 真实 API 在 `18007` 端口启动；两个独立 Worker 进程同时竞争同一 run，仅一个领取并完成。
- 真实 API 验证创建与幂等重试返回同一 run、排队取消，以及诊断信息明确未运行 Agent 规划。
- 真实数据库直接模拟进程中断：旧租约过期后 recovery Worker 接管并递增 fencing；旧 Worker 的迟到完成返回拒绝，新持有者成功完成。

验收脚本为 `backend/scripts/check_runs.py`，输出状态为成功。临时 API、容器和资源在收尾时清理。

## 4. 边界与未验证项

- `completed` 只表示本轮无副作用诊断 runner 完成，不表示已有采购/出行方案。
- 未实现 SSE、网页 run 界面、LangGraph、意图识别、LLM/MCP Agent 执行或 Java 服务扩展。
- SQLite 仅用于快速反馈；真实并发领取、租约恢复和 fencing 结论来自 PostgreSQL 17。