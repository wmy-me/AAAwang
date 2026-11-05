# 022：Agent 职责与包结构整理

- 状态：部分完成；代码入口和职责文档已整理，真实 shopping-mcp 组合回归受阻，不能据此宣称 022 已完成
- 所属阶段：P4 真实信息与更多采买场景（现有 Agent 架构收敛）
- 起始分支与代码提交：`main` / `0f8d10b5e4513414573a7f86405b0ff63814e634`；执行前重新核对 HEAD
- 前置证据：[020 报告](../reports/020-model-capability-budget-report.md)、[021 报告](../reports/021-dynamic-task-forms-report.md)
- 对应报告：`docs/reports/022-agent-responsibility-structure-report.md`

## 1. 问题与目标

020 和 021 已验收模型能力决策、真实 MCP 发现与白名单、共享预算、购物委派及动态表单。代码尚分散在 `agents/shopping.py`、`modules/capabilities/routing.py`、`worker/runner.py` 和 `modules/shopping_plans/service.py`。与此同时，`agents/coordinator/`、`discovery/`、`procurement/` 仍是预留目录，`agents/README.md` 与根 `CLAUDE.md` 的“尚无图/目录为空”等说法已过时。

本任务让现有已验证的职责在代码和文档中有明确归属，同时保留用户看到的任务、Run、候选、方案和动态表单行为。验收重点是代码职责清晰且生产调用路径确实使用整理后的模块；创建空 Agent 类或仅改目录说明不算完成。

## 2. 先读与核对

先读根 `AGENTS.md`、`CLAUDE.md`、`docs/progress.md`、[Agent 架构](../design/agent-architecture.md)、[执行与预算规则](../design/agent-execution-rules.md)、[Tools 与 MCP](../design/tools-and-mcp.md)、[数据保护与幂等](../design/security-and-idempotency.md)和 020/021 的任务及报告。查看 `agents/shopping.py`、`modules/capabilities/routing.py`、`worker/runner.py`、`modules/shopping_plans/service.py`、`core/budget.py`、`core/llm/tool_loop.py`、`tools/mcp/client.py` 及其调用方/测试，列出当前真实执行路径、职责和重复逻辑；不得按旧 README 猜测现状。

## 3. 本次范围与职责边界

| 归属 | 本次职责 |
| --- | --- |
| `agents/coordinator/` | 组织已存在的结构化模型能力决策、直答/追问、受控委派与结果汇总；接收受信任务目标、revision、消息及可见能力；模型只能从后端交集选择 |
| `agents/discovery/` | 承接现有购物信息发现与地图/商品只读能力适配，使用通用 MCP 客户端和已注册白名单；返回有来源和模拟标记的证据 |
| `agents/procurement/` | 明确已存在的购物候选到方案的职责边界；金额、数量、来源与引用校验继续由确定性服务复算，不为了目录完整而伪造独立 ReAct Agent |
| `worker/runner.py` | 保留领取 Run、租约、续期/fencing、取消、终态事务与执行分派；从整理后的 Agent 入口取得决策和结果，避免继续堆积领域提示词、图节点和模型输出解析 |
| `modules/capabilities/`、`tools/`、`modules/shopping_plans/` | 分别保持受信能力策略/可见集、通用工具传输、确定性方案与持久化职责；按实际依赖调整调用，不让模型决定服务 URL、身份或金额 |

先确定公开入口、状态与结果契约，再按依赖逐步移动现有实现。可保留 `agents/shopping.py` 作为兼容入口或在迁移调用方后移除，须核对所有 import；不要同时维护两套实际运行的购物图或两套预算计数。条件边只表达允许的决策和返回路径，不把地点→商品→规划固定为每次必经链路。012 的单次委派与 020 的能力决策不得被描述为完整开放式 ReAct。

`agents/travel/` 只更新真实状态说明；本任务不实现出行子图、天气/搜索、RAG、长期记忆、LangGraph checkpointer、下单或支付，也不新增外部 MCP/数据库表。

## 4. Agent 执行与预算契约

- 主协调使用当前已验收的受限模型结构化决策；购物发现保持现有有界工具循环，采买金额与数量由代码校验。清楚标注哪些路径是条件图、哪些是 Worker 分派或确定性服务，不以目录名称冒充多 Agent 能力。
- 020 已实现的 `RunBudget` 必须随同一个 Run 在模型决策、专业委派、工具发现和执行间共享；调用前预占，失败尝试计数。保持现有模型、委派、MCP、总远端调用与墙钟上限、一次有界纠正和停止原因，不因重组增加调用或重置预算。图递归上限仅作兜底。
- 能力可见集仍为后端注册策略、任务域、Agent、服务配置、真实 `list_tools()` 名称/schema 的交集；执行前复核。旧 Run、旧能力快照和 021 表单确认后的 Run 沿原有合同读取。
- 需变更提示词或调用顺序时，在报告中列明旧新路径与预算差异，并用真实场景证明行为。不要仅为满足目录结构引入无必要的额外模型调用或强制委派。

## 5. 数据保护与幂等

本任务原则上不新增业务字段、凭据、外部写操作或迁移。若执行中确需新增，先按数据保护与幂等规则说明敏感等级、owner/task/revision/Run 归属、存储和日志、唯一约束、并发及恢复策略，再明确记录范围变化。保持现有任务/表单消息与 Run 幂等、旧 revision 可读、双账号隔离、取消与失租 fencing；工具返回和模型输出不能提升权限。外部只读 MCP 的重试不承诺 exactly-once。

## 6. 执行步骤

1. 以最新 HEAD 核对代码、020/021 报告及目录 README；画出现有调用链和职责映射，记录将移动与保留的符号、兼容入口、风险。
2. 先建立稳定的 Agent 输入/输出契约和受信依赖注入，再逐步归位协调与发现逻辑；保持 `worker/runner.py` 的持久化生命周期职责和能力注册白名单的独立性。采买方案复算仍由现有确定性服务承担。
3. 更新生产调用方和相关测试；删除仅由重组产生的重复实现。旧 Run 类型、消息、表单、SSE 与网页结果接口保持兼容。
4. 更新 `agents/` 各 README、根 `CLAUDE.md`、`docs/progress.md` 中与实际代码冲突的状态文字；设计文档明确“现已实现/未来目标”，不要把后续出行与开放式 ReAct 写成已完成。
5. 按第 7 节验证；形成报告并同步任务索引及路线图状态。

## 7. 验收标准

- **结构**：生产 Run 确实调用整理后的 Agent 入口；`coordinator/` 与 `discovery/` 有可运行职责，`procurement/` 对现有确定性规划职责有准确说明或代码边界；无重复生效的购物图、模型路由和预算实例。Worker 仍负责 Run 生命周期，MCP 客户端仍可替换服务。
- **模型与工具**：用真实 DeepSeek、独立 Worker、PostgreSQL、高德 MCP 与 Java 模拟商品 MCP 回归无工具直答、缺条件追问、只查地点、只查商品、地点+商品组合；记录能力快照、来源/模拟标记、共享预算和终态。正常测试替身可覆盖内部边界，不能代替至少一轮真实组合路径。
- **动态表单**：021 的明确采购目标经表单确认后仍可按模型选择生成有效方案；无预算探索不被强制填表；旧表单/旧 Run、任务版本与结果重读正确。
- **失败与隔离**：未注册工具、错服务或 schema 变化不扩大可见集；预算耗尽、取消和失租不绕过停止/fencing；两个用户不能读取彼此任务、Run 或证据。复用已验收的覆盖，并针对迁移入口做有意义的回归。
- **工程与文档**：后端相关及全量测试、Ruff、编译、Alembic check、前端 lint/build 通过；若 Java 代码未变，可引用 020 的 Java 验证并明确本轮未重跑。文档中不再称已存在的购物图为“尚未创建任何图”，报告区分真实联调与替身证据。

如真实服务或环境不可用，明确列为未验收并保留任务未完成状态，不用历史报告代替新入口验证。

## 8. 完成后的文档与停止条件

创建 `docs/reports/022-agent-responsibility-structure-report.md`，记录起止提交、职责迁移表、旧新执行路径、实际命令/结果、真实/替身验证和剩余风险。同步 `docs/progress.md`、本目录索引、`docs/roadmap.md` 与相关 README。完成以上验收后才标记 022 完成，并停止；搜索、天气、投稿和出行另建后续编号任务。
