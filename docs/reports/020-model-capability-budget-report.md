# 020 模型能力决策与跨 Agent 共享预算报告

## 状态

已完成。共享预算、结构化模型能力决策、直答/追问、地图/商品/组合执行、决策与预算持久化均已完成，并用真实 DeepSeek、独立 Worker、PostgreSQL、高德 MCP、Java 模拟 MCP 验证了直答、缺城市追问、纯地点、纯商品和地图+商品五类场景。

**本轮规则执行结果**：任务 §2.1 的结构化模型能力决策已接入聊天 Run 的 Worker 生产路径。聊天入口先创建 `capability_decision` Run，Worker 使用共享预算请求固定 JSON，再由后端校验决策类型、注册能力、可见交集和地图位置条件，之后复用既有能力执行分支；完成时把解析后的执行类型与能力快照写回 Run。旧 `shopping_agent`、`shopping_research` 和 `direct_answer` Run 保持兼容。能力决策前和选定能力执行前均通过受信 `McpClient.list_tools()` 获取真实工具/schema，并重新计算白名单交集；服务不可用、工具下线或 schema 不兼容时不会暴露能力。网页已显示决策、能力快照、预算计数和终止原因。预算耗尽、取消、超时、租约过期和注入式失租已用独立 Worker 进程验证，决策/预算摘要已通过真实 Chromium 刷新重读。受控 MCP 联调已覆盖服务关闭、工具下线/改名、错服务、schema 不兼容和执行前二次校验；schema 校验要求注册的必填字段仍存在，真实高德和 Java 商品工具继续可见。

## 实现内容

- 新增 `RunBudget` 与 `BudgetLimits`：模型请求、专业委派、MCP 尝试、总远端调用和墙钟预算均在调用前预占；失败尝试也消耗额度；锁保证并发分支共享同一预算；取消、失败和超时可记录终止原因。
- MCP 能力发现（`list_tools()`）也以 `discovery` 预占共享远端预算，与决策前/执行前的两次发现一致；发现本身不增加 `mcp_attempts`，但会计入 `remote_calls`。
- 能力元数据新增输入 schema、独立超时、模型/远端预算消耗；新增受信交集计算，要求注册策略、任务域、启用服务和实际发现工具/schema 同时满足。模型或远端返回不能增加权限。
- 注册输入 schema 现在声明真实必填字段（商品 `keyword`、地图 `keywords`）；发现 schema 缺少这些必填字段、类型不符或工具名/服务 ID 不匹配时能力不可见。此前空 `required` 使 schema 兼容检查只能比较 `type`，无法识别必填字段变化。
- 购物 Agent、工具循环、地图调用和 Worker 透传同一个预算对象；组合 Run 的地图与商品分支不会各自重置额度。
- `DIRECT` 请求创建 `direct_answer` Run，由一次无工具模型文本调用完成，不创建商品候选、地点或方案证据；缺城市追问同样创建 `direct_answer` Run，但由 Worker 按持久化决策直接返回追问文本，不调用模型。
- `runs` 新增 nullable `decision` 和 `budget` JSON 字段，迁移为 `20261104_0016`；完成、失败、取消均保存可重读预算摘要。旧 Run 的 `capability_ids`、`decision`、`budget` 为 `NULL` 时保持兼容。
- 前端 Run 类型已包含能力快照、决策和预算摘要；现有结果读取 API 纳入 `direct_answer`。
- 聊天任务轮次不再在 API 事务中用关键词直接决定能力；模型决策只允许选择后端交集中的能力，未知能力、重复能力、错误结构和缺位置均被拒绝或降级为追问。模型把工具选择误标为 `direct` 但给出合法 ID 时，按 `capabilities` 归一化；ID 仍须通过可见集校验。
- 完成 Run 时写回解析后的 `execution_type` 与 `capability_ids`，网页刷新后可按实际能力读取地点/商品证据。
- `_discover_capability_tools()` 只使用服务端配置的 MCP service ID，调用真实 `list_tools()` 并提取服务端 schema；模型永远不能提供 URL、服务 ID 或工具名来扩大集合。执行前再次发现，拒绝能力变化。
- Run 详情网页展示决策类型、决策来源、能力快照、模型/MCP/远端计数和终止原因；刷新后通过私有 Run 详情重新加载这些字段。
- `fail_exhausted_runs()` 为最大尝试后的失租 Run 写入 `budget.termination_reason=lease_expired`；预算异常分别保留模型、MCP、远端耗尽或 `timeout`，取消保留 `cancelled`。
- 能力决策调用显式使用 512 completion tokens；此前 128 token 会在多字段 `form_schema` 中被截断成无效 JSON。`_termination_reason()` 统一把预算异常、`TimeoutError`、租约丢失和购物总时限映射为有界终止原因。

## 验证

- `uv run pytest -q`：`128 passed`。
- `uv run ruff check src scripts tests`：通过。
- `uv run python -m compileall -q src scripts tests`：通过。
- `uv run alembic upgrade head`：已应用 `20261104_0017`（020 字段由 `20261104_0016` 引入）。
- `uv run alembic check`：通过；数据库中保留既有表循环警告，但无新增迁移操作。
- `npm run lint`：通过，保留 3 条 React Hook warning（含 021 新增的 1 条）。
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

### 真实 Worker 终止与浏览器验证（2026-11-04）

停止常驻 Worker 后，用独立 Worker 子进程、真实 DeepSeek、PostgreSQL、高德 MCP 和 Java `shopping-mcp` 逐项执行：

| 场景 | Run ID | 证据 |
| --- | --- | --- |
| 取消 | `2214666d-e441-4b3c-bcee-5e663d1f2004` | Run 运行中调用取消 API；Worker 在检查点结束为 `cancelled`，`budget.termination_reason=cancelled` |
| 真实租约过期 | `36077f7d-36a8-4a5c-ad7a-57ff5fd5a6a2` | Worker 执行中把租约改为已过期；第一次外部调用的迟到完成被 fencing 拒绝，Run 被重新领取为 `attempt=2` 并完成；两个 `run.running` 事件、仅 1 条 assistant 消息，证明迟到写入未落库 |
| 租约耗尽 | `4438e542-58c8-432a-86cf-f2be9805218e` | 构造 `attempt=3` 且租约过期的 running Run；真实 Worker 的 `fail_exhausted_runs()` 将其置为 `failed`，`termination_reason=lease_expired` |
| 失租终止分支 | `8b479d5b-80ec-45b8-a793-631cf1829916` | 测试用 Worker 在数据库租约仍有效时注入一次续租失败；执行结束为 `failed`，`budget.termination_reason=lease_lost`，错误为“购物Agent执行租约丢失” |
| 模型预算耗尽 | `b6356055-5ffd-4725-b9d0-e76fed3b56d5` | 独立 Worker 以测试用 `BudgetLimits(model_requests=0)` 执行；失败原因 `model_budget_exhausted` |
| 远端预算耗尽 | `1a2ceb67-b322-4865-aaa5-c50d8746b9b7` | 独立 Worker 以测试用 `BudgetLimits(remote_calls=0)` 执行；失败原因 `remote_budget_exhausted` |
| 超时 | `27206308-58c0-4e16-b94f-866a87343800` | 独立 Worker 设置 `SHOPPING_AGENT_TOTAL_TIMEOUT_SECONDS=0.01`；真实决策后购物执行超时，失败原因 `timeout` |

补充说明：预算耗尽和失租终止分支使用独立 Worker 进程中的测试用预算/续租覆盖，不修改生产配置；真实租约过期时的实际行为是 fencing 拒绝迟到写入并重新领取，而不是直接写 `lease_lost`。这两点已如实写入边界。

网页验证使用本机缓存 Chromium（Playwright 无头）完成真实登录、表单提交和刷新；Run 详情在刷新前后均显示“决策/直接回答 · 模型、能力快照/无工具、预算/模型 2 · MCP 0 · 远端 2”，无错误提示（Run `849b1f0d-c195-46e6-bbe4-e9e7e30dcb8b`，任务 `32302b69-b049-4e4e-abde-f2453b3ca2d4`）。

### 受控 MCP 可见性联调（2026-11-04）

停止常驻 Worker 后，用独立 Worker 进程和 `MCP_SERVICES` 环境覆盖逐个场景执行。`service_closed` 使用关闭的本地端口；`tool_down`、`tool_renamed`、`wrong_service`、`schema_incompatible` 和 `execution_revalidation` 使用真实 Streamable HTTP MCP Python SDK 服务端，不是单元替身。

| 场景 | 发现结果（真实 `list_tools()`） | Run 终态与错误 |
| --- | --- | --- |
| 服务关闭 | `enabled=[]`、`visible=[]` | Run `0c31e3d6-5a35-4b86-8dbc-db176aeb6110` `completed`/`direct_answer`；无错误；模型说明当前无可用能力，未调用业务 MCP |
| 工具下线（服务可达但无工具） | `enabled=[shopping]`、`shopping=[]`、`visible=[]` | Run `8f02e966-07ee-4afd-94dc-703a2b1ed21a` `completed`/`direct_answer`；无错误 |
| 工具改名（`search_products_v2`） | `enabled=[shopping]`、`discovered=[search_products_v2]`、`visible=[]` | Run `ae96b74d-2257-49ab-b418-124fe9c52be9` `completed`/`direct_answer`；无错误 |
| 错服务（同名工具挂在 `other`） | `enabled=[other]`、`discovered=[search_products]`、`visible=[]` | Run `dc1a6c67-08fc-4723-89a8-70389b6549c5` `completed`/`direct_answer`；无错误 |
| schema 不兼容（必填字段由 `keyword` 变为 `query`） | `enabled=[shopping]`、`discovered=[search_products]`、`visible=[]` | Run `d7e8db82-607d-46d4-a7c6-9cb49ba77f5b` `completed`/`direct_answer`；无错误 |
| 执行前二次校验（首次发现后移除工具） | 决策阶段可见商品能力；执行前发现为空 | Run `c0f510c9-fae9-4f70-a507-29d9fba9cd54` `failed`；`error_summary=执行前 MCP 工具发现结果已变化，能力不可用。`；`model_requests=1`、`remote_calls=2` |

受控服务要求 `search_products` 必须声明 `required=["keyword"]` 才真实可见；这推动了注册 schema 的上述修正。真实高德和 Java 商品服务在修正后仍发现 `visible=[shopping_product_discovery, map_place_search]`，并重新完成纯地点 Run `22801a1f-5680-48bd-bb9a-0ddcf96cc52b`、纯商品 Run `771e7ac4-c888-407b-8ac4-41307b4960b5` 和组合 Run `1c7f6e44-e842-41f4-9065-1dbe736582bd`（20 个地点、1 个模拟候选、预算计数共享）。

替身测试补充覆盖跨 Agent 作用域（`agent_id=planner` 时可见集为空）、缺失注册必填字段和类型不兼容；跨 Agent 没有注册能力，因此没有真实协议场景。

## 边界与限制

- 五类真实决策已执行并通过；模型偶发把工具选择标成 `direct`，合法 ID 会被归一化为 `capabilities`，未知或不可见 ID 仍被拒绝。
- 服务关闭、工具下线/改名、错服务、schema 不兼容和执行前二次校验已用受控真实 MCP 协议验证；跨 Agent 作用域没有注册能力，使用替身测试覆盖。
- 取消、超时、租约过期和预算耗尽已用真实 Worker 进程验证；真实租约过期不会留下 `lease_lost` 终态，而是由 fencing 拒绝迟到写入并重新领取，`lease_lost` 分支只在续租失败且租约仍有效时记录（本轮用注入验证）。
- 预算耗尽场景使用独立 Worker 进程内的 `BudgetLimits` 覆盖，生产配置仍为默认上限；没有新增可调预算环境变量。
- 网页已用无头 Chromium 验证决策/预算摘要刷新重读；未执行有头浏览器人工交互，终止原因标签的浏览器展示未单独截图验收。
- 现有 PostgreSQL 中 36 条 `decision/budget` 为 NULL 的旧 Run 已用 `RunResponse` 验证可读；012–019 的 API/Run 回归由现有测试覆盖，未使用历史账号逐条浏览器重读。
- 本轮用户提供的验证结果中 `./mvnw -B -ntp verify` 已通过，shopping-mcp 的 6 个测试及 travel/local-life 模块成功；本轮没有 Java 改动。这只证明 Java 工程构建与测试通过，不替代真实 Worker/MCP 浏览器验收。

本轮没有加入新的外部服务、写操作、凭据或业务金额字段；外部 MCP 仍仅为只读调用，失败与重试不承诺 exactly-once。
