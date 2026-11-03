# 私有 Run 事件与 SSE REST 契约

Run 事件只属于创建该 Run 的用户。身份来自服务端会话 Cookie；不存在或不属于当前用户的 Run 统一返回 `404`。事件只保存安全摘要，不包含 Cookie、密钥、完整条件快照或堆栈。

## 事件模型

每个事件具有 `id`、`run_id`、单个 Run 内从 1 开始递增的 `sequence`、`event_type`、`occurred_at` 和结构化 `payload`。允许的事件类型为：

- `run.queued`
- `run.running`
- `run.cancel_requested`
- `run.completed`
- `run.failed`
- `run.cancelled`

状态转换和事件写入在同一数据库事务中提交。007之前创建的 Run 不补造历史事件，因此它们可能没有事件，但当前状态仍可由 `GET /api/runs/{run_id}` 读取。

## 补读接口

`GET /api/runs/{run_id}/events?after=0&limit=100`

返回 `sequence > after` 的已提交事件，按 `sequence` 升序排列。`after` 为 `0` 到 `1000000000` 的整数，`limit` 为 `1` 到 `100`。响应包含 `next_after`，无新事件时保持传入游标。

匿名请求返回 `401`，越权或不存在返回 `404`，参数非法返回 `422`，数据库不可用返回 `503`。

## SSE接口

`GET /api/runs/{run_id}/events/stream`

响应类型为 `text/event-stream`。支持查询参数 `after` 或 `Last-Event-ID` 请求头，游标为非负十进制整数且不超过 `1000000000`；两者同时提供且不一致时返回 `422`。连接建立前完成会话与 Run 归属检查，因此未知 Run 不会先返回 `200`。

每个业务事件发送稳定的 SSE `id=sequence`、`event=event_type` 和 JSON `data=payload`。服务先补发游标之后已经提交的事件，再以有界数据库轮询等待新事件；心跳是 SSE 注释，不表示业务进度。Run 到达 `completed`、`failed` 或 `cancelled` 且已补发全部事件后关闭流。客户端可保存最后一个事件 ID 并重连补读。

客户端断开后停止轮询并释放请求资源。数据库故障发生在流建立前时返回 `503`；建立后无法再改变 HTTP 状态，服务结束该流，客户端应使用最后事件 ID重连。

用户或任务删除时，数据库级联删除其从属Run及事件；任务新增revision不会删除历史Run。购物Run仍只发送受控阶段和终态摘要，不在事件中输出密钥、完整模型原文或完整工具原始结果；回答和受限来源通过私有结果接口读取。012的主 Agent 委派事实、决策类型和调用次数通过私有结果接口读取。010/012不提供模型 token 流、真实下单或交易结果。
