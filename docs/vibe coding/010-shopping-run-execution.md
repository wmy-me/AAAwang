# 010：购物任务 Run 接入有限模型与 MCP 查询

- 状态：已完成；真实 DeepSeek→shopping-mcp→PostgreSQL 购物 Run 闭环与外部调用中断恢复已实测，外部调用不承诺 exactly-once；见[报告](../reports/010-shopping-run-execution-report.md)
- 所属阶段：P2 持久化执行接入；为 P3 首条采买闭环提供基础
- 起始分支与代码提交：`main` / `adbe1314fb006bb19828267f0ed163845cfa2478`；实施前核对最新 HEAD
- 前置：[003 有限 LLM/MCP 闭环](003-llm-mcp-tool-loop.md)、[007 Run/Worker](007-persistent-runs-worker.md)、[008 事件/SSE](008-run-events-sse.md)、[009 删除链与并发回归](009-run-deletion-events-regression.md)均已提交
- 对应报告：`docs/reports/010-shopping-run-execution-report.md`
- 目标：登录用户为自己的购物任务某一条件版本创建 run；Worker 调用已有 DeepSeek 与 Java 模拟商品 MCP，持久化受控回答、来源及失败状态；用户通过私有接口重读，事件流显示阶段和终态

## 1. 先读和边界

先读 `CLAUDE.md`、[进度](../progress.md)、[路线图](../roadmap.md)、[Agent 设计](../design/agent-architecture.md)、[工具设计](../design/tools-and-mcp.md)、[run 契约](../../contracts/rest/runs.md)、[事件契约](../../contracts/rest/run-events.md)、[购物工具契约](../../contracts/mcp/README.md)及 003、007–009 报告。核对 `backend/src/life_agent/core/llm/tool_loop.py`、`worker/runner.py`、`modules/runs/service.py`、`modules/tasks/schemas.py` 和测试；不要照搬脚本作为 HTTP 处理函数。

当前 003 在独立脚本中只进行最多两次模型请求和一次 MCP 工具调用。007–009 的 Worker 是无外部副作用诊断 runner，`completed` 不含 Agent 回答。010 的业务执行只能在明确指定的购物 run 上启用，不得自动把旧诊断 run 当成真实模型任务。

## 2. 本轮工作

1. 明确创建 run 的**执行类型**：保留已存在 run 的 `diagnostic` 语义；新增只接受 shopping domain 的 `shopping_research`（或等价受控值），服务端按 task.domain 检查，用户不能提交服务 URL、工具名、owner 或自由执行代码。绑定创建时 task 的 goal、revision、conditions 快照；已有 run 数据迁移要兼容。travel 域仍只能保持诊断语义，不执行购物工具。
2. Worker 按执行类型分派，购物路径**复用** `run_tool_loop` 的鉴权后受信配置：默认 `shopping` 服务、允许工具 `search_products`；结合 goal 与条件生成受控查询上下文，不让客户端或模型自行扩大工具集合。若预算、物品、数量缺失，能明确写出已知/未知，不把缺失字段猜成既定条件。工具无结果、模型直接回答、超时、未配置 Key 或 MCP 不可用要有确定的成功/失败规则和安全错误。
3. 持久化一次运行的最终文本及最小来源证据（服务 ID、工具名、模拟标志、实际候选摘要或受限原始结果、执行版本、时间）；限制大小、过滤秘密和不可信 HTML。新建结果表或合适的单 run 结构，接口按 run 归属查询；旧诊断结果保持可读。助手消息若需写入，必须与 run/task/conversation 关联并去重，不能让失败重试生成两个相同回答。本轮可先通过 run 结果 API 查看回答，网页聊天另做。
4. 运行中状态、取消和 SSE：沿用 007–009 的数据库租约与 fencing。现有模型总超时默认 90 秒，Worker 租约默认 30 秒，实施者必须解决**执行时租约续期或明确的超时/回收策略**，防止慢模型期间被第二个 Worker 领取。网络调用前后检查取消和持有权；过期 Worker 的结果不能提交。状态事件保持事务性，增加必要的受控阶段/结果事件，不在事件中输出密钥或完整模型原始内容。
5. **成本与重试边界。** LLM 调用和 MCP 调用可能已经发生，即使 Worker 随后崩溃；不能把 DB 事务当成外部请求的 exactly-once 保证。针对购物运行明确中断后的策略：优先将有不确定外部执行历史的 run 标记为失败/需人工重试，不自动无限重放付费调用；新 run 用新的幂等键显式触发。保留 007 无副作用诊断 runner 原有恢复策略。
6. 更新 `contracts/rest/runs.md`、事件契约、`backend/.env.example` 和开发指南，写明启动 PostgreSQL、shopping-mcp、API、Worker 及本机配置 `LLM_API_KEY` 的方式。仓库自带开发 PostgreSQL 可独立启动；若用户本地 5432 已占用，使用自定端口并同步 `DATABASE_URL`。无需 MySQL、Redis、pgvector、MinIO 或第三方地图/搜索 Key。

## 3. 验收

| 场景 | 通过标准 |
| --- | --- |
| 真正闭环 | 在真实 PostgreSQL 17、真实 Java shopping-mcp 和有效 DeepSeek Key 的隔离测试下，创建购物 run → Worker 调用受限 MCP → 私有结果持久化 → 新客户端重读回答及模拟来源；SSE 可补读阶段与终态 |
| 用户与版本 | A/B 不能跨用户读取运行/结果/事件；修改 task 条件后旧 run 仍引用旧快照；travel 不调用购物 MCP |
| 资源安全 | 模型慢于旧 30 秒租约时不会被双 Worker 重复执行；取消、进程中断、旧 Worker 迟到提交、Key/MCP 缺失各有确定状态；外部调用不承诺 exactly once |
| 结果真实 | 回答引用实际工具候选并标记“模拟”；模型直接回答不能冒称已查过商品；空结果与失败不伪造价格 |
| 回归 | 001–009 Python 测试、真实 PG 迁移/并发、Java shopping 模块相关构建、Ruff、编译与锁文件检查通过 |

可先用替身测试故障分支，但**不能用替身结果宣称真实 DeepSeek→MCP→DB 链路通过**。如本地缺少有效 Key、端口/数据库未启动或实际调用失败，在报告中明确写“部分完成/受阻”及未验证项；不将脚本 003 的历史成功当成本轮成功。不要要求用户把密钥发到仓库或聊天中。

## 4. 完成与停止

提交 `docs/reports/010-shopping-run-execution-report.md`，记录起始提交、数据库迁移、真实/替身验证、实际模型和 MCP 调用次数、模拟来源、恢复与费用边界；更新 [进度](../progress.md)、[任务索引](README.md)、契约和开发指南。完成后停止。

010 不是完整多 Agent：不新增主从 Agent 图、自动意图路由、规划组合、预算硬校验、旅游、真实外部 MCP、RAG、网页聊天或订单。下一步再以真实 run 结果为输入拆主协调与信息发现/采买规划的委派，及网页对话展示。
