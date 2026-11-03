# 购物候选快照 REST 契约

候选快照通过 `GET /api/runs/{run_id}/shopping-artifacts` 返回，不接受客户端写入。响应中的 `candidates` 是该 Run 实际采用的 MCP 候选，按 `product_id` 去重，并包含 `id`、`product_id`、`name`、`unit_price`、`currency`、`unit`、`distributable_units`、`availability`、`source_type`、`source_service`、`simulated`、`quoted_at` 和 `queried_at`。来源为 Java `shopping-mcp` 的模拟商品时 `simulated=true`；这不表示实时库存、报价或下单结果。

请求需要登录。Run、task、revision 和 owner 必须属于当前用户；否则返回 `404`。
