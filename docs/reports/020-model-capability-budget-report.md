# 020 模型能力决策与跨 Agent 共享预算报告

## 状态

部分实现。共享预算、结构化模型能力决策、直答/追问、地图/商品/组合执行、决策与预算持久化均已完成，并用真实 DeepSeek、独立 Worker、PostgreSQL、高德 MCP、Java 模拟 MCP 验证了直答、缺城市追问、纯地点、纯商品和地图+商品五类场景。

**本轮规则执行结果**：任务 §2.1 的结构化模型能力决策已接入聊天 Run 的 Worker 生产路径。聊天入口先创建 `capability_decision` Run，Worker 使用共享预算请求固定 JSON，再由后端校验决策类型、注册能力、可见交集和地图位置条件，之后复用既有能力执行分支；完成时把解析后的执行类型与能力快照写回 Run。旧 `shopping_agent`、`shopping_research` 和 `direct_answer` Run 保持兼容。能力决策前和选定能力执行前均通过受信 `McpClient.list_tools()` 获取真实工具/schema，并重新计算白名单交集；服务不可用、工具下线或 schema 不兼容时不会暴露能力。网页已显示决策、能力快照、预算计数和终止原因。预算耗尽、取消、超时和失租已有代码/数据库专项验收，真实 Worker 逐项联调与真实浏览器刷新仍待补，因此本任务仍不能标记为完成。

## 实现内容

- 新增 `RunBudget` 与 `BudgetLimits`：模型请求、专业委派、MCP 尝试、总远端调用和墙钟预算均在调用前预占；失败尝试也消耗额度；锁保证并发分支共享同一预算；取消、失败和超时可记录终止原因。
- MCP 能力发现（`list_tools()`）也以 `discovery` 预占共享远端预算，与决策前/执行前的两次发现一致；发现本身不增加 `mcp_attempts`，但会计入 `remote_calls`。
- 能力元数据新增输入 schema、独立超时、模型/远端预算消耗；新增受信交集计算，要求注册策略、任务域、启用服务和实际发现工具/schema 同时满足。模型或远端返回不能增加权限。
- 购物 Agent、工具循环、地图调用和 Worker 透传同一个预算对象；组合 Run 的地图与商品分支不会各自重置额度。
- `DIRECT` 请求创建 `direct_answer` Run，由一次无工具模型文本调用完成，不创建商品候选、地点或方案证据；缺城市追问同样创建 `direct_answer` Run，但由 Worker 按持久化决策直接返回追问文本，不调用模型。
- `runs` 新增 nullable `decision` 和 `budget` JSON 字段，迁移为 `20261104_0016`；完成、失败、取消均保存可重读预算摘要。旧 Run 的 `capability_ids`、`decision`、`budget` 为 `NULL` 时保持兼容。
- 前端 Run 类型已包含能力快照、决策和预算摘要；现有结果读取 API 纳入 `direct_answer`。
- 聊天任务轮次不再在 API 事务中用关键词直接决定能力；模型决策只允许选择后端交集中的能力，未知能力、重复能力、错误结构和缺位置均被拒绝或降级为追问。模型把工具选择误标为 `direct` 但给出合法 ID 时，按 `capabilities` 归一化；ID 仍须通过可见集校验。
- 完成 Run 时写回解析后的 `execution_type` 与 `capability_ids`，网页刷新后可按实际能力读取地点/商品证据。
- `_discover_capability_tools()` 只使用服务端配置的 MCP service ID，调用真实 `list_tools()` 并提取服务端 schema；模型永远不能提供 URL、服务 ID 或工具名来扩大集合。执行前再次发现，拒绝能力变化。
- Run 详情网页展示决策类型、决策来源、能力快照、模型/MCP/远端计数和终止原因；刷新后通过私有 Run 详情重新加载这些字段。
- `fail_exhausted_runs()` 为最大尝试后的失租 Run 写入 `budget.termination_reason=lease_expired`；预算异常分别保留模型、MCP、远端耗尽或 `timeout`，取消保留 `cancelled`。

## 验证

- `uv run pytest -q`：`123 passed`。
- `uv run ruff check src tests`：通过。
- `uv run python -m compileall -q src tests`：通过。
- `uv run alembic upgrade head`：已应用 `20261104_0016`。
- `uv run alembic check`：通过；数据库中保留既有表循环警告，但无新增迁移操作。
- `npm run lint`：通过，保留既有 2 条 React Hook warning。
- `npm run build`：通过。
- 预算并发预占、能力交集、schema 不兼容、禁用服务和旧 Run 兼容使用替身测试覆盖；动态发现变化、预算耗尽/取消/超时和失租终态专项测试通过。
- 结构化决策替身覆盖合法地图能力、未注册能力拒绝、缺位置降级、`direct` + 合法 ID 归一化、代码围栏 JSON 解析和旧 Run 兼容。

### 真实联调（2026-11-04，模型决策路径）

重启后端与独立 Worker 后，用真实 DeepSeek、PostgreSQL、高德 MCP、Java `shopping-mcp` 执行 020 脚本。所有 Run 初始类型为 `capability_decision`，完成后写回实际类型与能力快照：

| 场景 | Run ID | 决策与结果 |
| --- | --- | --- |
| 无工具直答 | `17c673f3-70e3-4021-a018-431e3d639368` | 模型 `direct`；完成类型 `direct_answer`；预算 `model_requests=2`（决策+直答）、`remote_calls=2`（决策前发现 shopping/map），`mcp_attempts=0`；结果无候选、无地点 |
| 缺城市追问 | `9a5fa9f6-1c27-4d2c-a917-144251620c33` | 模型 `clarification`；完成类型 `direct_answer`；追问文本可重读；预算 `model_requests=1`、`remote_calls=2`（决策前发现），未调用业务 MCP |
| 纯地点查询 | `201c7f71-5447-4151-817e-502fdab31397` | 模型选择 `map_place_search`；完成类型 `map_places`；预算 `model_requests=1`、`mcp_attempts=1`、`remote_calls=5`（两次发现各 2 次 + 1 次地图调用）；高德返回 20 个上海书店 |
| 纯商品查询 | `fc530b4f-7d58-4727-8b7d-f00f4a2ff8fc` | 模型选择 `shopping_product_discovery`；完成类型 `shopping_agent`；预算 `model_requests=5`、`delegations=1`、`mcp_attempts=1`、`remote_calls=5`（两次发现各 2 次 + 1 次商品调用）；返回 3 个模拟候选 |
| 地图+商品组合 | `02b62ad5-5a15-4787-8bb3-54f54c6c24a9` | 模型选择两项能力；完成类型 `capability_router`；预算 `model_requests=4`、`delegations=1`、`mcp_attempts=2`、`remote_calls=6`（两次发现各 2 次 + 2 次业务调用）；高德返回 20 个地点，商品返回 2 个候选并生成有效方案 |

第二账号对上述 Run 的详情、结果、地点和商品制品请求均返回 404。`combo_map_source` 未出现在结果读取响应中，地点证据以 `/map-places` 为准。

## 真实与未验收边界

- 五类真实决策已执行并通过；模型偶发把工具选择标成 `direct`，合法 ID 会被归一化为 `capabilities`，未知或不可见 ID 仍被拒绝。
- 生产决策已使用后端在 Worker 中实时获取的受信 MCP `list_tools()` 结果；真实服务关闭、工具下线或 schema 不兼容的专项联调仍待补。
- 预算耗尽、取消、失租和超时已完成代码/SQLite 数据库专项验收；真实 Worker 进程与外部调用中的取消/失租窗口仍待逐一联调。
- 网页已渲染 `decision`/`budget`/终止原因；真实浏览器刷新重读尚未执行。
- 本轮已执行 `./mvnw -B -ntp verify`，shopping-mcp 的 6 个测试及 travel/local-life 模块均成功；这只证明 Java 工程构建与测试通过，不替代真实 Worker/MCP 浏览器验收。

本轮没有加入新的外部服务、写操作、凭据或业务金额字段；外部 MCP 仍仅为只读调用，失败与重试不承诺 exactly-once。
