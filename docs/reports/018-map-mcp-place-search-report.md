# 018 真实地图 MCP 地点查询最小接入报告

## 结论

018 部分完成真实高德地图 MCP 的只读地点查询接入。根目录 `.env` 使用拆分后的 `MAP_MCP_*` 配置；真实 Key 仅从本地环境注入，不写入报告、响应、Run 或模型上下文。地点查询现在可从选定购物任务对话或网页地点入口创建受控 `map_places` Run，结果按 owner、task、revision、Run 持久化，不进入 `shopping_candidates`，不参与商品价格和预算计算。

已完成的验收项是真实高德 MCP 初始化、工具发现和一次 POI 查询，以及配置、适配器、认证 API、任务内 `map_places` Run、地点持久化、网页入口和路由解析测试。真实浏览器/PostgreSQL 地点闭环尚未验收，认证/协议/限流/超时等 HTTP 错误细分仍未实现，因此本任务不能整体标记完成。

## 实现

- `MCP_SERVICES` 保留 shopping-mcp 的兼容配置；地图使用 `MAP_MCP_URL`、`MAP_MCP_KEY`、`MAP_MCP_TIMEOUT_SECONDS`、`MAP_MCP_ENABLED` 和 `MAP_MCP_TOOL_NAME`。
- 通用 MCP 客户端支持受限的认证查询参数拼接，禁止服务 URL 预置认证参数；适配器对外异常统一为通用文本，不回显认证值。
- 地图适配器固定 service ID、工具 allowlist、城市必填、查询长度、结果数量和文本长度；只保留名称、地址、坐标、电话、链接及来源字段。
- 任务内地点请求识别为受控 `map_places` execution type，沿用任务 revision、Run 幂等键、取消和 fencing；单次查询默认 20 秒超时，低于默认 30 秒租约，未单独实现长查询续租；缺城市时不调用 MCP，而是持久化澄清回答。
- 新增 `map_places` 表及迁移 `20261104_0014`，新增私有 `GET /api/runs/{run_id}/map-places`；地点结果可在 Run 完成后刷新读取。
- 网页加入城市/关键词地点入口、队列状态、来源/工具/时间和结果展示；商品 Run 仍读取商品 artifacts。
- 兼容高德真实返回：POI JSON 位于 MCP 文本内容块，不是 `structured_content`。
- 保留认证保护的 `GET /api/maps/places?query=礼品店&city=上海`；任务内结果使用 Run API。未配置返回 503，外部调用失败返回 502。

## 真实高德验收

- Streamable HTTP 初始化成功。
- MCP 协议：`2025-03-26`。
- 服务：`amap-sse-server`，版本 `1.0.0`。
- `list_tools` 成功，实际发现 `maps_text_search`，与 allowlist 一致。
- 真实查询：`keywords=礼品店`、`city=上海`、`citylimit=true`。
- 返回 `is_error=false`，经适配器规范化后得到 20 个 POI。
- 返回来源标记：`service_id=map`、`tool=maps_text_search`、`simulated=false`，并记录 UTC `observed_at`。
- 真实查询输出未记录 Key；高德返回的地点没有统一坐标时，坐标字段保持未知，不自行推断。

## 替身与回归验证

- 地图/MCP 聚焦测试：5 passed（使用替身连接，不消耗真实配额）；任务地点城市/关键词解析测试：7 passed。
- 后端全量测试：73 passed。
- `uv run ruff check src migrations tests`：通过。
- `uv run python -m compileall -q src scripts tests`：通过。
- 本地开发数据库已执行 `alembic upgrade head`（`20261103_0013` → `20261104_0014`），随后 `alembic check` 通过，无新迁移操作；未在独立空库上复验升级/降级。
- 前端 `npm run lint`：通过（2 条既有的 React Hook 警告）；`npm run build`：通过。
- 本任务未修改 Java 服务，未重新执行 Java 构建。

## 验收对象区分

- 真实外部服务：高德官方 MCP 的 Streamable HTTP 初始化、`list_tools` 和一次只读 POI 查询已执行；报告未记录凭据。
- 真实模型：本次未重新执行 DeepSeek→地图的真实任务回合；任务内地图分支是服务端受控路由，不允许模型选择 URL 或工具。
- 真实数据库：本地 PostgreSQL 已升级到 `20261104_0014`；未执行真实地点 Run 写入和刷新读取，SQLite 替身覆盖模型与 Run 回归。
- 浏览器：未执行本轮地点入口的真实浏览器操作；前端构建已通过。
- Java 模拟 MCP：本任务未调用；回归测试覆盖了既有 Python 测试，不等同于重新验收 shopping-mcp 真实链路。

## 未完成与验收边界

- 真实网页与 PostgreSQL 地点闭环尚未验收：代码已有地点入口、Run 刷新 API 和持久化模型，本地迁移已执行，但本轮未执行浏览器和真实地点 Run 写入/刷新证据。
- 当前是服务端关键词路由，不是完整 Graph 意图路由；工具白名单仍由受信地图配置固定，未实现按任务上下文生成能力组。普通商品消息不会调用地图，地点结果不会进入商品规划。
- 错误未细分：未配置返回 503，其余握手、认证、协议、限流和超时统一返回 502 通用文本；合法空结果返回空 `places` 列表并保留来源和时间。任务要求的错误区分未完整满足。
- 缺位置时任务对话会返回澄清回答且不调用 MCP；独立 API 仍返回 422。城市/关键词解析按固定模式匹配，未接入完整意图识别。
- 认证查询参数由 MCP SDK 在传输层携带；适配器不把 Key 写入响应、Run 或模型上下文，异常统一包装。未对第三方 SDK 的全部内部日志做额外脱敏审计。

本次真实证据只覆盖高德 MCP 初始化、工具发现和一次只读 POI 查询，不代表路线、天气、真实商品价格、库存、下单或跨系统 exactly-once。Java shopping-mcp 仍是独立的模拟商品来源；地图查询失败不会生成假店铺，也不会改变现有购物金额复算。
