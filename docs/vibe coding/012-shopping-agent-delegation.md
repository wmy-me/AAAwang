# 012：购物主 Agent 与信息发现 Agent 的最小委派

- 状态：已完成；真实 API/Worker/PostgreSQL 闭环、空结果/候选结果、用户隔离和 SSE 终态补读已验收
- 所属阶段：P2 Agent 执行基础；为 P3 首条采买闭环提供委派能力
- 起始分支与代码提交：`main` / `83e95161cb69bc31d63d7b0c12eb5b391a0af3a2`；执行前重新核对 HEAD，保留期间已有改动
- 前置任务：[010 购物 Run 报告](../reports/010-shopping-run-execution-report.md)和[011 数据库配置报告](../reports/011-dev-database-config-report.md)
- 对应报告：[012 执行报告](../reports/012-shopping-agent-delegation-report.md)

## 1. 问题与目标

目前 `shopping_research` Run 由 Worker 直接调用 `run_tool_loop`；已有真实 DeepSeek→Java 模拟购物 MCP→PostgreSQL 闭环，但 `agents/` 还没有主 Agent、专业 Agent 或实际 LangGraph 路径。要让主 Agent 根据目标和当前任务版本决定：无需查询即可答复、缺少关键条件时追问，或委派信息发现 Agent 查询模拟候选。信息发现只负责发现与汇报证据，主 Agent 负责用户可读回复。委派必须由模型基于工具描述与当前目标选择，不能按字符串关键字写死，也不能只把原有工具循环改名为 Agent。

此轮仍通过现有私有 Run API 发起和读取结果；不等同于网页聊天或完整采买方案。用一个可运行的 LangGraph 图（或在当前锁定版本上由 `create_agent` 构建的实际 LangGraph 图）表达主 Agent 调用专业能力的控制路径，清楚记录调用事实与受限结果。可以选择“专业 Agent 包装为委派工具”实现，只有确需跨图共享状态时才使用 handoff/`Command`；同一执行内不同时实现两套并行框架。

## 2. 开始前阅读与核对

先读根 `CLAUDE.md`、[进度](../progress.md)、[路线图](../roadmap.md)、[任务索引](README.md)、[Agent 分工](../design/agent-architecture.md)、[意图识别](../design/intent-routing.md)、[工具与 MCP](../design/tools-and-mcp.md)、[Run 契约](../../contracts/rest/runs.md)和 010、011 报告。核对 `backend/src/life_agent/agents/`、`core/llm/`、`tools/mcp/`、`modules/runs/`、`worker/runner.py`、`db/models.py` 及现有测试、迁移。执行前确认当前 LangGraph/LangChain、DeepSeek SDK 与 MCP 客户端的实际版本和可用 API；接口随版本变化时以已安装版本和官方文档为准，不照搬本文假设的方法名。

## 3. 本次范围与外部契约

1. 新增显式 `shopping_agent` Run 执行类型，仅限已认证用户自己的 `shopping` task 与指定的 `expected_revision`；继续使用 007–010 的入队、快照、幂等、Worker、租约、取消、事件和结果私有读取。保留 `diagnostic`、`shopping_research` 的现有语义与兼容性；若 API 和存储类型需扩展，先核对约束并用 Alembic 正式迁移，不能直接改旧迁移。
2. 主 Agent 从可信服务端接收 goal 与绑定的 conditions 快照，输出三种可辨别结果：`direct_answer`、`clarification`、`delegated_discovery`。只在查询有实际价值时向信息发现 Agent 委派。明确的条件缺口可追问，但缺预算不自动阻止只读候选查询；不能自造预算、数量、报价或已查询事实。
3. 信息发现 Agent 的可见工具仅限后端配置的 `shopping` MCP 服务中明确允许的只读 `search_products`；复用已有通用 MCP 初始化、发现、schema 校验、工具名映射、超时和结果上限。委派只传本任务必要条件，不能由模型选择任意服务 URL、用户 ID、任务 ID、工具名或执行代码。MCP 内容与工具描述均为不可信输入，不能提升权限。
4. 信息发现输出受限结构化摘要：是否实际调用、服务与工具身份、模拟来源、候选或空结果、缺失项、错误，以及必要的安全截断信息。主 Agent 根据这些证据形成最终答复；没调用工具时不得声称“已查到商品”，模拟价格必须显著标记。空结果是正常查询结果，不伪造候选；错误不伪装成空结果。
5. `GET /api/runs/{run_id}/result` 应支持所属用户读取已完成 `shopping_agent` 结果。沿用 `shopping_run_results` 或为确有必要的新字段增加正式迁移，至少持久化回答、决策类型、是否委派、实际 MCP 调用次数、模拟来源和执行版本；不可把内部推理、密钥、认证头或完整未截断的远程正文写入事件/结果。失败或取消沿用现有终态约定。更新 REST 与事件契约，并明确旧结果格式的兼容行为。

## 4. 执行约束与设计取舍

- 专业 Agent 作为主 Agent 的有名称和准确描述的委派能力，描述写清“何时查询商品候选、何时不要用、返回什么”。主 Agent 的模型工具调用是委派的事实证据；仍需由代码校验被选能力、参数和状态。可采用工具包装子 Agent；要在实现与报告中指出实际图结构、跳转或调用关系，不把单次普通 LLM 分类器加固定 if 伪称多 Agent。
- 首版仅一次委派、最多一次远程购物查询；模型请求数、总耗时、工具调用数和委派次数设置共享上限并由代码强制。未得到完整结果时不进入无限循环；拒绝额外、未知或越权委派。保留可注入模型/MCP 客户端的可测试边界。
- 保持 Worker 的续租、fencing 和终态同事务写入约束。每次重要模型或 MCP 请求前后检查取消/租约；无法保证请求进行中立刻停止时，应在报告解释中断窗口。外部请求在进程崩溃前可能已发生，禁止承诺 exactly-once 或无条件重放不确定历史。
- 任务版本及归属由 API/DB 校验后传入图；图状态仅保留本次运行需要的字段。此轮不增加长期对话记忆、跨任务路由或外部持久化 checkpointer；Run/结果/事件仍由现有 PostgreSQL 管理。不要在数据库里预建商品候选、规划方案等尚未使用的业务表。
- 用户本机根目录 `.env` 提供 DeepSeek Key 与现有连接配置，不把 Key 或密码发到对话或提交。Java shopping-mcp 是模拟外部 MCP，未来替换服务仍复用通用协议层。本轮不需要 MySQL、Redis、MinIO、地图、搜索、RAG、旅游 MCP 或真实商品平台。
- 明确检查并修复 [开发指南 5.4 节](../guides/development.md)被 011 误插入代码块的 Compose 表格行，恢复 `uv run python scripts/check_tasks.py` 命令；不顺势重写无关指南。

## 5. 实施顺序

1. 核对 011 HEAD 的代码和实际配置，先确定新类型、结果契约和最小图状态；记录与本文不一致的地方。
2. 实现主 Agent 的模型选择与信息发现委派，复用现有客户端和受控工具边界；先用针对性的测试替身覆盖三种选择、错误/空结果和额度约束。
3. 接入新 Run 类型、Worker 执行与现有持久化结果/事件；按需迁移并更新契约。保持 010 路径不变。
4. 用项目专用 PostgreSQL 和真实 Java shopping-mcp，在隔离测试用户/任务下验证真实 DeepSeek 自主委派；再验证直接答复或追问无 MCP 调用。核对新客户端重读、双用户隔离和旧 run 回归，结束时清理隔离测试数据，不清理数据库卷。
5. 更新开发说明、任务报告与进度；根据实际运行日志写明模型请求、委派及 MCP 调用次数和费用边界。

## 6. 验收标准

| 场景 | 可观察结果 |
| --- | --- |
| 主 Agent 决策 | 至少三类针对性样例中，模型可选择直接答、追问或委派；真实 DeepSeek + Java MCP 的委派样例证明图中发生了专业 Agent 调用，而非直接 Worker 工具循环 |
| 委派与证据 | 委派只暴露 `shopping:search_products`；实际候选、空结果、未知条件和模拟标记均准确；直接答复及追问未调用 MCP |
| 隔离与历史 | A/B 用户无法互读 run/结果/事件；结果绑定原条件快照，修改 task 后旧 run 不变；旧 `shopping_research` 和 `diagnostic` 回归通过 |
| 故障与资源 | 缺 Key、MCP 离线、非法委派、超时、额外工具调用、取消和租约丢失有受控状态；共享预算阻止循环，旧 Worker 不可提交迟到结果 |
| 持久化与回归 | PostgreSQL 迁移（如有）到 head、`alembic check`，新客户端读取决策/来源，SSE 补读终态；Python 全量测试、Ruff、编译、锁文件和相关 Java 构建通过；开发指南 5.4 命令恢复 |

替身测试只能证明分支与故障处理。真实模型自主选择委派、真实 MCP 连接与 PostgreSQL 重读需各有独立证据；若环境缺少可用 Key 或服务，报告写明已完成代码和未通过的真实验收，不把 010 历史验证当成 012 的通过证据。不要在报告粘贴密钥、密码、完整工具原文或模型内部推理。

## 7. 完成与停止

提交 `docs/reports/012-shopping-agent-delegation-report.md`，记录起始与最终提交、真实/替身验证、迁移、委派图、调用次数、旧路径回归、失败与恢复边界；同步 [任务索引](README.md)、[进度](../progress.md)、[路线图](../roadmap.md)、REST/事件契约及开发指南。只有关键真实闭环通过后才标记“已完成”；部分完成须明确缺口。完成本任务后停止，网页聊天、完整意图识别、候选/方案业务表、P3 奖品组合、RAG 和出行另建编号任务。
