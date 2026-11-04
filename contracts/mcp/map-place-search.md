# 地图地点查询契约

## `GET /api/maps/places`

认证保护的只读查询。`query` 是地点关键词，`city` 是用户明确提供的城市或位置范围；服务端不会读取设备定位，也不会猜测地点。独立 API 的结果只在当前响应中展示；选定任务内的 `map_places` Run 按 owner、task、revision、Run 持久化，可通过 `GET /api/runs/{run_id}/map-places` 刷新读取。地点结果不进入 `shopping_candidates` 或购物金额计算。

请求示例：`/api/maps/places?query=礼品店&city=上海`

成功响应包含：

- `places`：白名单字段 `name`、`address`、`location`、`phone`、`url` 和 `source`。
- `source.service_id`、`source.tool`、`source.simulated=false`。
- `observed_at`：服务端接收结果的 UTC 时间。

错误：

- `401`：没有有效登录会话；上游地图鉴权失败时也返回 `401`，响应 `detail.code=authentication_failed`。
- `422`：关键词或城市缺失/超过 120 个字符，或上游请求参数被拒绝（`detail.code=invalid_request`）。
- `429`：上游限流或额度受限（`detail.code=rate_limited`）。
- `503`：地图 MCP 未配置或未启用（`detail.code=not_configured`）。
- `504`：上游超时（`detail.code=timeout`）。
- `502`：协议不兼容、工具未发现或外部调用失败（`detail.code=protocol_error` 或 `external_failure`）。

地图查询错误使用 `{"code": "...", "message": "..."}` 的 `detail`，消息为固定安全文本，不回显上游异常或认证 URL。

高德 Streamable HTTP 使用后端秘密配置的 `key` 查询参数；密钥不进入请求响应、日志、Run 或模型上下文。该 API 首版不承诺跨外部服务 exactly-once，重复只读查询可能消耗供应商额度。