# 033 高德 MCP 周边地点搜索报告

- 状态：已完成
- 日期：2026-11-06
- 任务：[033](../vibe%20coding/033-amap-nearby-search.md)

## 实现

- 复用既有 `map_place_search` 能力、地图结果持久化、私有 API/SSE、Worker、RunBudget、租约和取消链路；没有新建 Worker、地图服务、前端表单或并行执行流程。
- 地图适配层新增受控 `geocode_address()` 和 `search_nearby_places()`。地址/地标查询先调用真实 `maps_geo(address)`，取得唯一坐标后调用 `maps_around_search(keywords, location, radius, strategy)`；用户直接给坐标时跳过地理编码。默认半径是可配置的后端值 `MAP_MCP_NEARBY_RADIUS_METERS=1000`，不是用户声称的距离。
- 保留原有城市关键词 `maps_text_search(keywords, city, citylimit)`。周边工具绝不复用其 city/citylimit 参数；地理编码与周边工具各在调用前动态发现、验证名称且受配置 allowlist 限制。
- 高德工具白名单新增 `MAP_MCP_NEARBY_TOOL_NAME` 与 `MAP_MCP_GEOCODE_TOOL_NAME`，默认分别为实际发现的 `maps_around_search` 与 `maps_geo`；既有 key 仍只由本地受保护配置注入，未输出或提交。
- Worker 对地址路径的地理编码和周边检索分别预占一次既有 MCP/remote 预算；坐标路径预占一次。空结果、服务故障和地址多匹配按既有错误/澄清路径处理；地点只保留名称、地址、坐标、来源和查询时间，不编造距离、营业状态、库存或价格。
- 032 意图和能力层仍由模型按需选择地图、商品、天气、网页或直答；附近地标可被识别为地图范围，但采购任务不会因此被强制调用地图。

## 真实高德验证

以现有受保护配置连接 `map` MCP，动态发现了 `maps_geo`、`maps_around_search` 和 `maps_text_search` 的真实 schema。主流程实际运行：地址“天安门” → `maps_geo` → `maps_around_search`，查询类别“餐厅”。周边工具返回 5 个真实地点；前三个名称为“四季民福烤鸭店(故宫店)”、“The Georg”、“国家大剧院西餐厅”。来源标记为 `map / maps_around_search`，不是 shopping MCP 模拟商品。

同一中心位置的“文具店”查询合法返回空集合，作为无结果分支证据；未把它写成服务失败或虚构地点。

## 聚焦检查

- `test_geocode_then_nearby_uses_distinct_server_generated_parameters`：Fake MCP 断言地址工具只收 `address`，周边工具只收 `keywords/location/radius/strategy`，通过。
- 复用城市文本搜索的缺城市澄清与 allowlisted POI 字段检查；附近地标只选择 `map_place_search`，未选择商品能力，均通过。
- 项目 Python 3.12 执行上述聚焦函数的替身运行结果为 `routing-focused-tests-ok`、`map-focused-tests-ok`；`compileall` 与 `git diff --check` 通过。

当前 `.venv` 仍没有 pytest/Ruff 开发依赖；本任务未运行全量回归、浏览器矩阵或完整 API/Worker 持久化烟测。没有下载 Embedding、运行 `uv sync`、执行 031 的真实 Mem0/pgvector 联调或启动备用 Compose。031 真实联调继续暂缓。
