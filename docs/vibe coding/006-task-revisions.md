# 006：私有任务与条件版本

- 状态：已完成；实现与验收见[报告](../reports/006-task-revisions-report.md)
- 所属阶段：P2 任务与对话基础
- 起始分支与代码提交：`main` / `76cea1ac874045c26182de6d6edc4aaaadfe5344`；实施前核对最新 HEAD，保留之后已有改动
- 前置：[004 账号认证](004-auth-foundation.md)和[005 私有对话与消息](005-private-conversations.md)均已提交并有执行报告
- 对应报告：`docs/reports/006-task-revisions-report.md`
- 目标：在一个对话中持久化多个独立目标及不可变条件快照，防止跨任务覆盖和并发丢失更新

## 1. 当前缺口与先读

005 只能保存手工消息。对话是容器，不等于一个业务目标；当前没有任务 ID、独立条件或版本，无法可靠处理“把奖品预算改为 500”而保留同一对话里的出行预算。

先读根 `CLAUDE.md`、[任务索引](README.md)、[当前进度](../progress.md)、[路线图](../roadmap.md)、[Agent 架构](../design/agent-architecture.md)、[意图路由设计](../design/intent-routing.md)及[初始设计包第 7、10 节](../design/生活采买智能体_项目初始设计包.md)。核对现有 `backend/src/life_agent/db/models.py`、`modules/conversations/`、`api/dependencies.py`、`migrations/`、`contracts/rest/conversations.md` 和 005 测试。初始设计包是参考，不照搬旧接口。

## 2. 本轮范围

- 一个 `conversation` 可包含多个 `task`。任务具有稳定 ID、归属对话、目标描述、领域/类型、当前条件版本号和时间戳；每个 `task_revision` 是完整且不可原地修改的条件快照，包含任务 ID、单调版本号、条件、创建时间与可选变更说明。条件不只藏在聊天文字或模型回复。
- 首版只通过用户**明确指定**的 API 创建和修改任务，不自动从消息猜测任务，也不调用 LLM。领域至少可表示 shopping 与 travel 两类独立目标；首版条件 schema 明确限制 JSON 对象大小、深度及已知字段（如预算、人数、目的地、日期）的类型和缺失含义。尚不做实际采购/行程规划，不把任意自由 JSON 直接当作正式执行参数。
- 新增 Alembic 迁移、外键、唯一约束和必要索引。创建 task 与 revision 1 原子提交；新快照与当前版本指针原子更新，历史快照保留。与已有 users、conversations、messages 兼容。
- 身份只从 004 的 `CurrentUser` 获取，任务归属经 owner 范围内的对话验证；不能由请求体、模型或 MCP 提供 owner ID。A/B 的任务、条件、列表、历史互相隔离；不存在与越权统一不泄漏存在性的 404。写接口沿用现有 Origin/Fetch Metadata 防护。

建议接口（最终约定写在 `contracts/rest/tasks.md`）：

| 接口 | 行为 |
| --- | --- |
| `POST /api/conversations/{id}/tasks` | 在自己的对话创建任务和第 1 版快照 |
| `GET /api/conversations/{id}/tasks` | 分页列出该对话下自己的任务 |
| `GET /api/tasks/{id}` | 读取当前版本和条件摘要 |
| `GET /api/tasks/{id}/revisions` | 稳定分页读取不可变历史 |
| `POST /api/tasks/{id}/revisions` | 携带 `expected_revision` 提交新条件并返回新版本 |

明确更新请求是完整快照还是受控字段 patch；如果是 patch，基于当前版本合并后仍保存完整新快照。过期 `expected_revision` 返回 409 和当前版本号，不能覆盖另一个修改。使用真实数据库约束与原子条件更新/行锁等防止并发的两个同版本提交都成功。相同条件是否创建新版本应有确定规则及测试。任务 ID 必须明确指定，不能根据最近消息推断。

## 3. 实施与验收

1. 核对最新仓库，定义类型、条件 schema、版本冲突语义；建迁移与服务层，然后加 API 和契约。应用启动不自动建表。
2. 聚焦测试双用户资源归属、同对话两个任务的预算/地点隔离、历史快照不可变、旧版本 409、两个请求同时改同版本至多一个成功、非法字段和停库安全错误。
3. 在真实 PostgreSQL 上从已迁移 005 的库升级，核对重复升级、迁移一致性、双账号、双任务、并发冲突与新客户端重读；替身测试与真实数据库结果分别记录。
4. 运行现有 001–005 回归、Ruff、编译和锁文件检查；未修改 Java/网页时无需重复无关构建。

| 场景 | 通过标准 |
| --- | --- |
| 持久化与隔离 | A 同一对话建两个任务；B 不可向 A 对话创建、读写或列出任务；重连后 A 的版本仍可读取 |
| 条件版本 | 改奖品预算不改变出行条件；旧版保持不变；过期版本 409；真实并发更新只有一个成功 |
| 输入与故障 | 伪造身份、无效类型/条件被拒；匿名 401；越权与不存在同类 404；跨站写入被拒；停库不伪造成功 |
| 回归 | 005 的消息幂等、004 的认证与 001–003 最小模型/MCP 检查继续通过 |

本轮不创建 `run`、Worker、SSE、方案、助手消息或 LangGraph 图。003 命令行工具循环保持独立；不能因任务表存在就宣称可执行或恢复任务。

## 4. 完成后停止

创建 `docs/reports/006-task-revisions-report.md`，记录实际起始提交、迁移、真实 PostgreSQL 和替身检查、并发结果、未验证项；同步 `docs/progress.md`、[任务索引](README.md)、根 README 和开发指南。未满足验收时标记部分完成或受阻。

完成 006 后停止。持久化 run/Worker、事件/SSE、网页对话及 Agent 接入按后续编号任务逐步实施；不自动进入 P3。
