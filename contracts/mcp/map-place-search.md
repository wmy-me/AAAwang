# 地图地点查询契约

## `GET /api/maps/places`

认证保护的只读查询。`query` 是地点关键词，`city` 是用户明确提供的城市或位置范围；服务端不会读取设备定位，也不会猜测地点。结果只在当前响应中展示，不持久化，也不进入 `shopping_candidates` 或购物金额计算。

请求示例：`/api/maps/places?query=礼品店&city=上海`

成功响应包含：

- `places`：白名单字段 `name`、`address`、`location`、`phone`、`url` 和 `source`。
- `source.service_id`、`source.tool`、`source.simulated=false`。
- `observed_at`：服务端接收结果的 UTC 时间。

错误：

- `401`：没有有效登录会话。
- `422`：关键词或城市缺失/超过 120 个字符。
- `503`：地图 MCP 未配置或未启用。
- `502`：地图 MCP 握手、工具发现、认证、限流、超时或调用失败。

高德 Streamable HTTP 使用后端秘密配置的 `key` 查询参数；密钥不进入请求响应、日志、Run 或模型上下文。该 API 首版不承诺跨外部服务 exactly-once，重复只读查询可能消耗供应商额度。