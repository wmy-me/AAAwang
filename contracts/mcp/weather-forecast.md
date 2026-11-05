# 高德 MCP 天气查询契约

## 范围

023 在既有 `map` MCP 服务上接入只读 `maps_weather` 工具。它只返回公开天气预报，不执行穿衣推荐、出行编排、搜索或购买决策。

## MCP 工具

- 服务 ID：`map`
- 工具名：`maps_weather`
- 传输：配置的 Streamable HTTP MCP
- 请求：`{"city": "上海"}`
- 发现要求：`list_tools` 中必须存在该工具，且 schema 类型为 `object`、required 包含 `city`
- 调用权限：只允许后端注册的工具名和配置 allowlist；模型不能提交 URL、服务 ID 或工具名

## 归一化结果

适配器保留最多 7 条预报，并只保留以下字段：`date`、`week`、`day_weather`、`night_weather`、`day_temperature`、`night_temperature`、`day_wind`、`night_wind`、`day_wind_power`、`night_wind_power`。未知字段丢弃，缺失字段为 `null`。

来源保留 `service_id=map`、`tool=maps_weather` 和 `simulated=false`。外部读取可重试，但不承诺 exactly-once。

## 业务约束

天气请求必须明确城市；“天气怎么样”等无城市输入只生成澄清，不调用 MCP。结果按 owner、task、task revision、run 写入 `weather_snapshots`，通过认证的 `GET /api/runs/{run_id}/weather` 读取，越权或不存在统一返回 404。

天气与地点/商品组合仍使用同一个 Run 的共享预算、租约、取消、fencing 和终态事务；023 不实现旅行规划、穿衣推荐、交易或通用 Agent。
