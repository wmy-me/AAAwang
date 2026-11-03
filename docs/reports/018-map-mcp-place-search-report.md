# 018 真实地图 MCP 地点查询最小接入报告

## 结论

018 部分完成真实高德地图 MCP 的只读地点查询接入。根目录 `.env` 使用拆分后的 `MAP_MCP_*` 配置；真实 Key 仅从本地环境注入，不写入报告、响应、Run 或模型上下文。首版地点结果按请求返回，不持久化，不进入 `shopping_candidates`，不参与商品价格和预算计算。

已完成的验收项是真实高德 MCP 初始化、工具发现和一次 POI 查询，以及对应的配置、适配器、认证 API 和测试。任务要求的网页读取入口、选定购物任务内发起地点查询，以及认证/协议/限流/超时等错误的细分仍未实现，因此本任务不能整体标记完成。

## 实现

- `MCP_SERVICES` 保留 shopping-mcp 的兼容配置；地图使用 `MAP_MCP_URL`、`MAP_MCP_KEY`、`MAP_MCP_TIMEOUT_SECONDS`、`MAP_MCP_ENABLED` 和 `MAP_MCP_TOOL_NAME`。
- 通用 MCP 客户端支持受限的认证查询参数拼接，禁止服务 URL 预置认证参数；适配器对外异常统一为通用文本，不回显认证值。
- 地图适配器固定 service ID、工具 allowlist、城市必填、查询长度、结果数量和文本长度；只保留名称、地址、坐标、电话、链接及来源字段。
- 兼容高德真实返回：POI JSON 位于 MCP 文本内容块，不是 `structured_content`。
- 新增认证保护的 `GET /api/maps/places?query=礼品店&city=上海`；结果只在当前响应展示，未配置返回 503，外部调用失败返回 502。

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

- 地图/MCP 聚焦测试：5 passed（使用替身连接，不消耗真实配额）。
- MCP 客户端回归：6 passed。
- 后端全量测试：66 passed。
- `uv run ruff check src migrations tests`：通过。
- `uv run python -m compileall -q src scripts tests`：通过。
- `uv run alembic check`：通过，无新迁移操作；本任务未新增表或字段。
- 前端 `npm run lint`：通过（2 条既有的 React Hook 警告）；`npm run build`：通过。
- 本任务未修改 Java 服务，未重新执行 Java 构建。

## 验收对象区分

- 真实外部服务：高德官方 MCP 的 Streamable HTTP 初始化、`list_tools` 和一次只读 POI 查询已执行；报告未记录凭据。
- 真实模型：本任务未调用 DeepSeek，地点查询不经过模型或 `shopping_agent`。
- 真实数据库：本任务不持久化地点结果，未新增数据库读取或写入。
- 浏览器：未执行网页操作；当前只有认证 API，前端没有地图入口。
- Java 模拟 MCP：本任务未调用；回归测试覆盖了既有 Python 测试，不等同于重新验收 shopping-mcp 真实链路。

## 未完成与验收边界

- 网页不能读取地点结果：缺少前端请求封装和展示入口，任务验收表的“网页可按定义读取”未满足。
- 不能在选定购物任务内请求地点：当前只有独立的 `GET /api/maps/places`，没有接入对话、任务或 Run 的入口，任务 §3.4 的购物场景未满足。
- 未接入 Graph 条件路由与受信工具注册元数据：主协调不会按意图在追问、地点查询、商品查询或汇总之间选择；工具白名单仍由单个服务配置固定，未实现按任务上下文生成能力组。普通购物任务不会调用地图，独立地点 API 也不经过商品规划，但这是缺少接入而非条件路由的结果。
- 错误未细分：未配置返回 503，其余握手、认证、协议、限流和超时统一返回 502 通用文本；合法空结果返回空 `places` 列表并保留来源和时间。任务要求的错误区分未完整满足。
- 缺位置时 API 返回 422，但没有对话式追问入口。
- 认证查询参数由 MCP SDK 在传输层携带；适配器不把 Key 写入响应、Run 或模型上下文，异常统一包装。未对第三方 SDK 的全部内部日志做额外脱敏审计。

本次真实证据只覆盖高德 MCP 初始化、工具发现和一次只读 POI 查询，不代表路线、天气、真实商品价格、库存、下单或跨系统 exactly-once。Java shopping-mcp 仍是独立的模拟商品来源；地图查询失败不会生成假店铺，也不会改变现有购物金额复算。
