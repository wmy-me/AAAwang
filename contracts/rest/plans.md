# 结构化采买方案 REST 契约

`GET /api/runs/{run_id}/shopping-artifacts` 的 `plan` 为服务端复算的方案，或在候选为空、条件缺失、预算不足或 Agent 追问时为 `null`。有效方案包含 `revision`、`people`、`covered_people`、`budget`、`total`、`remaining`、`currency`、`unknown_fees`、`note` 和 `items`。每个 item 引用返回候选的 `candidate_id`，并包含包装数量、覆盖人数和 Decimal `subtotal`。

方案按 `run_id` 唯一，与 owner、task、不可变 revision 绑定；旧 revision 的方案可以读取，不能覆盖新 revision。`unknown_fees=true` 表示运费、税费和优惠未计入商品金额，不能解释为最终成交价。

## 手动调整

`POST /api/tasks/{task_id}/shopping-adjustments` 创建不可变手动版本。请求包含
`base_run_id`、`expected_revision`、`expected_adjustment_version`、稳定
`client_request_id` 和 `items[{candidate_id, package_quantity}]`；不接受客户端价格、
小计或总额。候选必须来自同一 owner/task/revision 的已完成 Run 快照，包装数量为正整数
且候选不可重复。

`GET /api/tasks/{task_id}/shopping-adjustments` 返回按版本倒序的历史和
`current_version`。同一请求 ID 与相同指纹重试返回原版本，不同指纹返回 409；版本前提
不匹配返回 409。服务端复算 Decimal 金额、覆盖人数、预算余量和未知费用语义，旧 Run 的
自动方案不被修改。
