# 023 高德 MCP 天气能力报告

## 状态

已完成。天气适配器、受控能力路由、Worker 分支、快照迁移、私有 API、网页展示、真实服务闭环和专项回归均已通过。

## 基线与范围

- 起始参考：022 已完成但为部分受阻的当前工作区；未撤销用户已有改动。
- 只扩展同一个高德 MCP 的只读 `maps_weather` 能力。
- 不实现旅行编排、穿衣推荐、购买决策、搜索、RAG 或通用 Agent。

## 实现

- `Settings` 增加 `map_mcp_weather_tool_name=maps_weather`，地图服务 allowlist 可同时包含地点和天气工具；地点适配器保留单工具旧配置兼容，并在多工具配置中使用显式地点工具。
- `weather.py` 执行 discovered schema 校验、固定参数调用、最多七天字段归一化和稳定错误码；Worker 在共享预算中预占 MCP 调用，并沿用 Run 取消、租约和 fencing 的终态路径。
- `weather_snapshots` 按 owner/task/task revision/run 保存；新增私有 `GET /api/runs/{run_id}/weather`，网页展示城市、来源、查询时间、日期、昼夜天气、温度和风力。
- coordinator/能力注册支持 `weather_forecast`；无城市输入返回澄清，不调用 MCP；组合能力不会建立固定天气链。
- 修复真实联调发现的中文请求前缀解析问题：`请查询上海天气` 现在提取为 `上海`，而不是把请求动词带入城市名；新增回归测试。

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
- 天气专项：`9 passed`，覆盖服务禁用、发现 schema 不兼容、合法空结果、超时和预算耗尽；天气/路由/Worker 相关：`35 passed`。
- 地图、购物、动态方案、共享预算和 Run 终态回归：`59 passed`；后端全量测试：`147 passed`。
- 前端 `npm run lint`：通过，保留既有 3 条 Hook warning；`npm run build`：通过。
- `alembic upgrade head`：已执行 `20261105_0018`，表创建成功。
- `alembic check`：首次发现 ORM 缺少 `ix_weather_snapshots_task_revision`，已补齐模型声明；最终检查无新升级操作。

## 真实浏览器与终止语义

- 已完成真实 Run `b4b788fc-0d7c-4864-ad18-32240b338416`：真实 DeepSeek 选择 `weather_forecast`，独立 Worker 执行一次真实 `maps_weather`，结果为 `上海市` 4 天预报；`execution_type=weather`，快照 API 200，事件包含 `run.completed`，第二账号读取快照 404。来源为 `service_id=map`、`tool=maps_weather`、`simulated=false`。
- 浏览器使用 `/usr/bin/google-chrome` 与仓库外 `/tmp/023-browser` 的 Playwright 完成：真实注册、创建“查询城市天气”任务、发送“请查询上海天气”，页面显示 `WEATHER / 上海市`、`map / maps_weather` 和 4 天预报；刷新后同一 Run、来源、城市和 4 天预报仍显示。页面验证账号为临时隔离账号 `weather023_browser_1793849370698`。
- 天气专项测试验证禁用服务、schema 不兼容、超时、合法空结果和预算耗尽；预算耗尽在 MCP 调用前终止。取消、失租、fencing 和终态事务沿用现有 Run 公共路径，相关 Run 回归包含在 `59 passed` 中，天气分支在完成前经过同一取消检查并由 `complete_claim` 统一防迟到写入。
- 本次真实联调曾发现并修复城市解析缺陷；修复后的真实 Run 返回 4 天非空预报。真实高德调用为外部只读请求，可重试但不承诺 exactly-once。
