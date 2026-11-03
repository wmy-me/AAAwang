# 结构化采买方案 REST 契约

`GET /api/runs/{run_id}/shopping-artifacts` 的 `plan` 为服务端复算的方案，或在候选为空、条件缺失、预算不足或 Agent 追问时为 `null`。有效方案包含 `revision`、`people`、`covered_people`、`budget`、`total`、`remaining`、`currency`、`unknown_fees`、`note` 和 `items`。每个 item 引用返回候选的 `candidate_id`，并包含包装数量、覆盖人数和 Decimal `subtotal`。

方案按 `run_id` 唯一，与 owner、task、不可变 revision 绑定；旧 revision 的方案可以读取，不能覆盖新 revision。`unknown_fees=true` 表示运费、税费和优惠未计入商品金额，不能解释为最终成交价。
