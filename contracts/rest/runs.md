# 私有持久化 Run REST 契约

Run 由当前用户明确为一个 task 的明确 revision 创建。身份只来自服务端登录 Cookie；任务或 run 不存在、或不属于当前用户时统一返回 `404`。写请求沿用受信 Origin 与 Fetch Metadata 检查。

## 创建与版本绑定

`POST /api/tasks/{task_id}/runs`

```json
{
  "expected_revision": 2,
  "idempotency_key": "client-generated-key",
  "execution_type": "shopping_research"
}
```

`execution_type` 默认为 `diagnostic`，保留007–009的无副作用语义；`shopping_research` 保留010的有限工具循环；`shopping_agent` 只接受 `shopping` task，使用主 Agent 委派信息发现 Agent。两种购物类型都只能使用后端固定的 `shopping` MCP 服务和 `search_products` 工具。客户端不能提交服务URL、工具名或执行代码。服务端在同一事务中锁定 task、核对 `expected_revision`，读取该版本不可变 revision，并复制完整 `conditions` 快照。响应包含 `task_revision_id`、`revision`、`conditions`、执行类型和 `status=queued`。之后 task 的 current revision 变化不影响该 run。

幂等键在同一 task 内唯一。相同 task、相同键和相同 revision 的重试返回同一 run；同一 task 使用该键但请求版本不同返回 `409`。

## 查询与取消

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/tasks/{task_id}/runs?offset=0&limit=50` | 按创建时间倒序列出当前用户该 task 的 run |
| `GET /api/runs/{run_id}` | 读取一个私有 run |
| `POST /api/runs/{run_id}/cancel` | queued 立即取消；running 设置协作式取消请求；终态重复取消返回原 run |

状态为 `queued`、`running`、`completed`、`failed` 或 `cancelled`。诊断Run的 `completed` 只表示无副作用 runner 完成；购物Run的 `completed` 表示有限查询链路完成，可通过 `GET /api/runs/{run_id}/result` 读取回答和受限模拟来源，不表示真实下单或交易。

## 购物结果

`GET /api/runs/{run_id}/result` 仅返回所属用户已完成的购物结果。`shopping_research` 返回010兼容字段；`shopping_agent` 另外返回 `decision_type`（`direct_answer`、`clarification` 或 `delegated_discovery`）、`delegated` 和 `mcp_call_count`。结果包含最终文本、实际服务/工具身份、模拟标志、受限候选摘要和执行版本。主 Agent 最多委派一次，信息发现最多调用一次 `search_products`；直接答复和追问的 MCP 调用次数为0。没有结果、非购物Run、失败或越权均返回 `404`。失败摘要不包含密钥、完整模型原始内容或不可信HTML。

## Worker 与故障

独立 Worker 用数据库行锁和 `SKIP LOCKED` 领取 queued run，或领取租约已过期且仍可重试的 run。每次领取递增 `attempt` 和 `fencing_token`，写终态必须匹配 `worker_id`、fencing token 且租约未过期；购物模型/MCP调用期间另有数据库心跳续租，旧 Worker 的迟到写入被拒绝。默认最多 3 次尝试，超过后为 `failed`。外部调用可能已发生而数据库写入失败，系统不承诺 exactly-once；不确定历史的购物Run应创建新的幂等键重试，不自动无限重放。

运行中取消在 Worker 检查点落为 `cancelled`，不是强杀线程。数据库不可用时 API 返回安全 `503`，不泄露连接信息或 Worker 堆栈。

## 状态码

| 状态 | 含义 |
| --- | --- |
| `401` | 缺少有效登录会话 |
| `403` | 跨站写请求被拒绝 |
| `404` | task 或 run 不存在，或不属于当前用户 |
| `409` | revision 已过期或幂等键冲突 |
| `422` | revision、幂等键、UUID 或分页参数无效 |
| `503` | 认证或 run 存储暂时不可用 |