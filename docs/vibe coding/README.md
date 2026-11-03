# AI 执行任务

此目录专门放供 Claude、Codex 等 AI 读取并执行的任务文档。产品规划与设计参考不作为自动执行指令。

## 使用规则

1. 先读根目录 `AGENTS.md`、`CLAUDE.md`、[文档导航](../README.md)、[当前进度](../progress.md)和用户本次指定的任务。
2. 查看最新分支、提交及已有实现，再核对任务的起始基线和前置条件。代码前进时保留已有工作，不机械复用旧命令。
3. 只执行本次指定范围。读到路线图、设计包中的后续步骤，不自动继续开发。
4. 一个任务对应一个可验证结果。实现前应有任务说明；实现后必须提交对应报告与进度更新。
5. 遇到可自行判断的常规细节继续推进；只有目标冲突、关键条件缺失或超出授权时才提出具体问题。任务文档不引入逐动作确认。
6. 外部工具的注册和调用需验证真实协议；普通 HTTP 健康接口不能代替 MCP 接通证据。
7. Java 模拟 MCP 与外部 MCP 沿用通用接入路径，模拟数据明确标注。不将当前 Java 实现写成 Agent 的固定依赖。
8. 报告区分真实模型、真实外部服务、Java 模拟服务和测试替身；未执行检查如实注明。
9. 新字段或有副作用的操作先读[数据保护与幂等规则](../design/security-and-idempotency.md)，在任务、契约和报告中写明敏感数据处理、归属校验、重复请求、并发及外部状态不明时的策略；不得将规则当成已实现证据。
10. Agent 任务先读[Agent 执行与预算规则](../design/agent-execution-rules.md)，写清角色、循环、共享调用预算、工具权限、停止条件和实际验收；首版提案不能写成已实现。

## 设计参考与执行范围

后续相关任务按需读取 [Agent、Tools、RAG 与意图识别设计](../design/README.md)。专题文档中的推荐配置和输出示例需要在具体任务中验证；保存讨论结论不会自动启动后续阶段，也不改变下表的任务状态。

## 命名与状态

- 任务：`NNN-主题.md`，使用三位递增编号。
- 报告：`../reports/NNN-主题-report.md`。
- 模板：[TEMPLATE.md](TEMPLATE.md)；模板不是执行任务。
- 状态：草案、待执行、执行中、已完成、受阻、已替代。状态必须与报告和代码核对，不能单凭一行“完成”认定验收通过。
- 已完成任务保留作追溯；范围变化新增任务或记录修订，不把历史验收改写成新的事实。

## 当前任务索引

| 编号 | 任务 | 状态与证据 |
| --- | --- | --- |
| 000 | [项目初始化](p0生活采买智能体_项目初始化执行文档.md) | 已执行；[报告](../reports/000-initialization-report.md)记录构建和健康检查，浏览器交互未验证 |
| 001 | [真实模型接入与最小调用验证](001-llm-connection.md) | 已完成；DeepSeek 实现、本地检查和一次真实请求均通过，见[报告](../reports/001-llm-connection-report.md) |
| 002 | [通用 MCP 客户端与 Java 模拟查询服务](002-mcp-integration.md) | 已完成；真实 Streamable HTTP 初始化、发现和模拟查询通过，见[报告](../reports/002-mcp-integration-report.md) |
| 003 | [LLM 与 MCP 的最小工具调用闭环](003-llm-mcp-tool-loop.md) | 已完成；真实 DeepSeek 发出 tool_call、MCP 查询及基于结果回答通过，见[报告](../reports/003-llm-mcp-tool-loop-report.md) |
| 004 | [账号认证与会话基础](004-auth-foundation.md) | 已完成；真实 PostgreSQL 迁移、服务端 Cookie 会话、CSRF 与代理联调通过，见[报告](../reports/004-auth-foundation-report.md) |
| 005 | [私有对话与消息持久化](005-private-conversations.md) | 已完成；真实 PostgreSQL 双用户隔离、持久化和消息幂等已通过，见[报告](../reports/005-private-conversations-report.md) |
| 006 | [私有任务与条件版本](006-task-revisions.md) | 已完成；真实 PostgreSQL 任务隔离、不可变快照和并发冲突保护已通过，见[报告](../reports/006-task-revisions-report.md) |
| 007 | [持久化 Run 与最小 Worker](007-persistent-runs-worker.md) | 已完成；版本绑定、幂等入队、独立 Worker 领取、取消、租约回收与 fencing 已通过真实 PostgreSQL，见[报告](../reports/007-persistent-runs-worker-report.md) |
| 008 | [持久化 Run 事件与 SSE](008-run-events-sse.md) | 已完成；[报告](../reports/008-run-events-sse-report.md)记录事件事务、私有补读、SSE 和真实 PostgreSQL 部分联调；完整并发事件与删除链另见 009 |
| 009 | [Run 删除链修复与事件真实并发回归](009-run-deletion-events-regression.md) | 已完成；[报告](../reports/009-run-deletion-events-regression-report.md)记录外键修复、存量迁移、删除链和真实事件并发验收 |
| 010 | [购物任务 Run 接入有限模型与 MCP 查询](010-shopping-run-execution.md) | 已完成；[报告](../reports/010-shopping-run-execution-report.md)记录受控执行、结果持久化、租约续期、真实 DeepSeek→shopping-mcp→PostgreSQL 闭环和外部调用中断恢复；外部调用不承诺 exactly-once |
| 011 | [项目数据库开发环境与配置收敛](011-dev-database-config.md) | 已完成；项目专用 PostgreSQL、单源配置、可选服务 profile；旧卷角色对齐、0007 迁移和 down/up 持久化已验证，未删除卷 |
| 012 | [购物主 Agent 与信息发现 Agent 的最小委派](012-shopping-agent-delegation.md) | 已完成；LangGraph 主从委派、shopping_agent、0008迁移、真实 API/Worker/PostgreSQL 闭环、用户隔离和 SSE 终态补读均通过，见[报告](../reports/012-shopping-agent-delegation-report.md) |
| 013 | [网页登录与购物 Agent Run 可视化](013-shopping-web-workbench.md) | 已完成；网页工作台、真实 Worker/MCP completed 结果、刷新恢复、双用户隔离、登出后刷新和独立 SSE 终态补读均通过，见[报告](../reports/013-shopping-web-workbench-report.md) |
| 014 | [已选购物任务的多轮对话与助手消息持久化](014-shopping-task-chat.md) | 已完成；两轮真实 Worker/DeepSeek/MCP、assistant 消息唯一持久化、幂等、跨账号和浏览器刷新重读均通过，见[报告](../reports/014-shopping-task-chat-report.md) |
| 015 | [教师奖品采买候选与结构化方案](015-shopping-candidates-and-plan.md) | 待执行；以 014 为前置，规划候选快照、金额复算、方案持久化和网页展示 |

P1 的 001–003 和 P2 的 004–014 均有实现与报告；013 的登出刷新与独立 SSE、014 的两轮任务对话与 assistant 消息持久化均已验收；015 为待执行的 P3 首条采买方案任务。

如需 Git 提交、推送或 PR，遵循本次用户指令和仓库约定；任务模板不自行授予发布权限。
