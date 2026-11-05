# 023 高德 MCP 天气能力报告

## 状态

部分完成/受阻。天气适配器、受控能力路由、Worker 分支、快照迁移、私有 API、网页展示和替身回归已实现；真实 MCP 协议调用已通过，但真实 DeepSeek 选择、独立 Worker + PostgreSQL + 浏览器端到端、双账号 404、取消/失租/预算天气专项证据尚未完成，因此不标记任务整体完成。

## 基线与范围

- 起始参考：022 已完成但为部分受阻的当前工作区；未撤销用户已有改动。
- 只扩展同一个高德 MCP 的只读 `maps_weather` 能力。
- 不实现旅行编排、穿衣推荐、购买决策、搜索、RAG 或通用 Agent。

## 实现

- `Settings` 增加 `map_mcp_weather_tool_name=maps_weather`，地图服务 allowlist 可同时包含地点和天气工具；地点适配器保留单工具旧配置兼容，并在多工具配置中使用显式地点工具。
- `weather.py` 执行 discovered schema 校验、固定参数调用、最多七天字段归一化和稳定错误码；Worker 在共享预算中预占 MCP 调用，并沿用 Run 取消、租约和 fencing 的终态路径。
- `weather_snapshots` 按 owner/task/task revision/run 保存；新增私有 `GET /api/runs/{run_id}/weather`，网页展示城市、来源、查询时间、日期、昼夜天气、温度和风力。
- coordinator/能力注册支持 `weather_forecast`；无城市输入返回澄清，不调用 MCP；组合能力不会建立固定天气链。

## 真实 MCP 证据

已使用当前项目 MCP 客户端对真实高德端点验证：

1. `initialize` 成功，协议为 `2025-03-26`。
2. `list_tools` 成功，发现 15 个工具，其中 `maps_weather` 的输入 schema 为 object，required 为 `city`。
3. `call_tool("maps_weather", {"city": "上海"})` 成功，返回上海四日预报，来源为真实高德 MCP，非 Java stub。
4. 通过 `life_agent.tools.maps.query_weather()` 适配器再次调用真实高德：返回 `city=上海市`、4 天预报，首个日期 `2026-11-05`，来源 `service_id=map`、`tool=maps_weather`、`simulated=false`。修复了适配器读取 `DiscoveredTool` schema 时使用错误属性的问题。

凭据未写入代码、日志、报告或模型上下文。

## 自动验证

- `uv run ruff check src tests`：通过。
- `uv run python -m compileall -q src tests`：通过。
- 天气、路由、地点回归：`27 passed`；后端全量测试：`142 passed`。
- 前端 `npm run lint`：通过，保留既有 3 条 Hook warning；`npm run build`：通过。
- `alembic upgrade head`：已执行 `20261105_0018`，表创建成功。
- `alembic check`：首次发现 ORM 缺少 `ix_weather_snapshots_task_revision`，已补齐模型声明；最终检查无新升级操作。

## 未完成与风险

- 尚未完成真实 DeepSeek -> 独立 Worker -> PostgreSQL 快照 -> API 刷新 -> 浏览器的完整证据链。
- 尚未完成第二账号天气读取 404、天气专项取消/租约丢失/预算耗尽验证。
- 真实高德调用为外部只读请求，可重试但不承诺 exactly-once。
