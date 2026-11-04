# 020 模型能力决策与跨 Agent 共享预算报告

## 状态

部分实现。已完成共享预算、直答/追问 Run、决策与预算持久化、能力元数据与工具交集计算，并完成真实 DeepSeek、独立 Worker、PostgreSQL、高德 MCP、Java 模拟 MCP 的直答、缺城市追问和组合 Run 联调。

**未实现的核心要求**：任务 §2.1 的结构化模型能力决策没有落地，`route_task_turn` 仍使用服务端正则规则；`visible_capabilities` 只在单元测试中调用，未接入聊天路由或 Worker 的生产执行路径。因此本任务不能标记为完成，019 的“结构化服务端路由”仍是当前实际路由方式。

## 实现内容

- 新增 `RunBudget` 与 `BudgetLimits`：模型请求、专业委派、MCP 尝试、总远端调用和墙钟预算均在调用前预占；失败尝试也消耗额度；锁保证并发分支共享同一预算；取消、失败和超时可记录终止原因。
- 能力元数据新增输入 schema、独立超时、模型/远端预算消耗；新增受信交集计算，要求注册策略、任务域、启用服务和实际发现工具/schema 同时满足。模型或远端返回不能增加权限。
- 购物 Agent、工具循环、地图调用和 Worker 透传同一个预算对象；组合 Run 的地图与商品分支不会各自重置额度。
- `DIRECT` 请求创建 `direct_answer` Run，由一次无工具模型文本调用完成，不创建商品候选、地点或方案证据；缺城市追问同样创建 `direct_answer` Run，但由 Worker 按持久化决策直接返回追问文本，不调用模型。
- `runs` 新增 nullable `decision` 和 `budget` JSON 字段，迁移为 `20261104_0016`；完成、失败、取消均保存可重读预算摘要。旧 Run 的 `capability_ids`、`decision`、`budget` 为 `NULL` 时保持兼容。
- 前端 Run 类型已包含能力快照、决策和预算摘要；现有结果读取 API 纳入 `direct_answer`。

## 验证

- `uv run pytest -q`：`114 passed`。
- `uv run ruff check src tests`：通过。
- `uv run python -m compileall -q src tests`：通过。
- `uv run alembic upgrade head`：已应用 `20261104_0016`。
- `uv run alembic check`：通过；数据库中保留既有表循环警告，但无新增迁移操作。
- `npm run lint`：通过，保留既有 2 条 React Hook warning。
- `npm run build`：通过。
- 预算并发预占、能力交集、schema 不兼容、禁用服务和旧 Run 兼容使用替身测试覆盖。

### 真实联调（2026-11-04）

重启后端与独立 Worker 后，用真实 DeepSeek、PostgreSQL、高德 MCP、Java `shopping-mcp` 执行 020 脚本：

| 场景 | Run ID | 结果 |
| --- | --- | --- |
| 无工具直答 | `e4d9e331-0d0b-4892-bfdf-bbb69c4c3ac0` | `direct_answer` 完成；`decision.kind=direct`；预算 `model_requests=1`，MCP/远端为 0；结果无候选、无地点 |
| 缺城市追问 | `07644545-c229-4000-8b2c-7678533c3181` | `direct_answer` 完成；`decision.kind=clarification` 且追问文本可重读；预算 `model_requests=0`，未调用模型或 MCP |
| 地图+商品组合 | `dc60d3f2-cde1-41a3-b014-5dfaf8c058f0` | `capability_router` 完成；能力快照为地图+商品；预算 `model_requests=3`、`delegations=1`、`mcp_attempts=2`、`remote_calls=2`；高德返回上海 20 个地点，商品返回 2 个候选并由服务端生成有效方案 |

第二账号对上述 Run 的详情、结果、地点和商品制品请求均返回 404。`combo_map_source` 未出现在结果读取响应中，地点证据以 `/map-places` 为准。

## 真实与未验收边界

- 结构化模型能力决策未实现，四类请求的能力选择仍由正则规则完成；真实模型未参与能力选择。
- 动态工具交集未接入生产执行，服务开关或工具下线不会改变聊天路由结果。
- 真实预算耗尽、取消、失租和超时终止未逐一联调。
- 网页只更新了 Run 类型定义，未渲染 `decision`/`budget`；真实浏览器刷新未执行。
- 本轮未重新执行 Java `verify`。

本轮没有加入新的外部服务、写操作、凭据或业务金额字段；外部 MCP 仍仅为只读调用，失败与重试不承诺 exactly-once。
