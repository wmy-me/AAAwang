# 私有任务与条件版本 REST 契约

任务属于一个私有对话。身份只来自服务端登录 Cookie；对话或任务不存在、或不属于当前用户时统一返回 `404`。写请求沿用受信 Origin 与 Fetch Metadata 检查。

## 数据模型

任务包含稳定 `id`、`conversation_id`、`domain`、当前 revision 的 `goal`、`current_revision`、当前完整 `conditions`、`goal_conflicts`、`goal_resolution`、`goal_legacy` 以及创建/更新时间。`domain` 首版仅允许 `shopping` 和 `travel`，`goal` 去除首尾空白后长度为 1–500。兼容字段 `Task.goal` 只作为当前 revision 投影。

每个 revision 是不可原地修改的完整目标与条件快照，包含 `id`、`task_id`、单调递增的 `revision`、`goal`、`conditions`、可空 `goal_conflicts`、`goal_resolution`、`goal_legacy`、`change_note` 和创建时间。创建任务时原子创建 revision 1。

## 条件规则

条件必须是 JSON 对象，编码后不超过 16 KiB。首版只允许以下可选字段；字段缺失表示用户尚未提供，不表示零值或系统默认值。

| domain | 字段 | 类型与约束 |
| --- | --- | --- |
| `shopping` | `budget` | 大于 0 的数字 |
| `shopping` | `people`、`quantity` | 大于 0 的整数 |
| `shopping` | `item` | 1–200 字符非空字符串 |
| `travel` | `budget` | 大于 0 的数字 |
| `travel` | `people` | 大于 0 的整数 |
| `travel` | `destination` | 1–200 字符非空字符串 |
| `travel` | `start_date`、`end_date` | `YYYY-MM-DD`；结束日期不能早于开始日期 |

未知字段、嵌套对象、数组、布尔值代替数字或类型不匹配均返回 `422`。服务端不会从消息、模型或 MCP 自动生成条件。

## 接口

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/conversations/{conversation_id}/tasks` | 创建任务及 revision 1，返回 `201` |
| `GET /api/conversations/{conversation_id}/tasks?offset=0&limit=50` | 列出该对话内当前用户的任务 |
| `GET /api/tasks/{task_id}` | 读取任务及当前完整条件 |
| `GET /api/tasks/{task_id}/revisions?offset=0&limit=100` | 按版本升序读取历史快照 |
| `POST /api/tasks/{task_id}/revisions` | 提交完整新快照，返回 `201` |

分页 `offset` 范围为 0–1,000,000，`limit` 范围为 1–100。任务按 `updated_at DESC, id DESC` 稳定排序，历史按 revision 升序。

## 更新与并发

修订请求格式：

```json
{
  "expected_revision": 2,
  "goal": "给 25 人购买奖品，总预算 180 元",
  "conditions": {"budget": 500, "quantity": 20},
  "change_note": "提高预算",
  "confirm_goal_conflict": false
}
```

`conditions` 是完整替换快照，不是 patch。即使新条件与当前版本相同，明确提交仍创建下一版本。服务端以 `expected_revision` 做数据库条件更新；两个请求同时基于同一版本时至多一个成功。

目标中明确识别的人数或预算与结构化条件冲突时，未确认的修订仍可保存并在任务卡展示冲突，但创建 Run 或任务聊天 turn 返回：

```json
{
  "detail": {
    "message": "任务目标与结构化条件存在明确冲突。",
    "goal_conflicts": [{"field": "budget", "goal_value": 200, "condition_value": 180, "fragment": "预算 200 元"}]
  }
}
```

提交 `confirm_goal_conflict: true` 时，服务端按结构化条件修正已识别冲突并记录 `goal_resolution`。无法可靠识别的数字只保留为不确定，不据此判断一致。结构化 `budget` 始终是复算依据。

过期版本返回：

```json
{
  "detail": {
    "message": "任务条件版本冲突。",
    "current_revision": 3
  }
}
```

历史 revision 不提供修改或删除接口。任务 ID 必须由客户端明确指定，不根据最近消息推断。

## 状态码

| 状态 | 含义 |
| --- | --- |
| `401` | 缺少有效登录会话 |
| `403` | 跨站写请求被拒绝 |
| `404` | 对话或任务不存在，或不属于当前用户 |
| `409` | `expected_revision` 已过期；响应含当前版本 |
| `422` | domain、条件、额外身份字段、UUID 或分页参数无效 |
| `503` | 认证或任务存储暂时不可用 |