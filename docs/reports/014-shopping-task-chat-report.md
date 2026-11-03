# 014 已选购物任务多轮对话与助手消息持久化报告

验收日期：2026-11-03
状态：**已完成**

## 1. 实现范围

已实现选中 shopping task 下的回合提交、消息与 TaskRevision/Run 关联、Worker 成功时的 assistant 消息写入、消息历史读取和网页聊天面板。0009 迁移建立 `messages.task_id`、`messages.run_id` 和 `runs.input_message_id`；0010 迁移把“每个 run 只能有一条消息”调整为“每个 run 至多一条 assistant 消息”。既有 005 手工消息接口和 007–013 Run API 保持兼容。

本轮补齐的稳定性修复：

- `claim_run()` 在数据库 Session 提交前固化 `task.goal` 和本轮用户消息，避免独立 Worker 对已关闭 Session 懒加载。
- 主 Agent 决策解析容错：接受代码块包裹的 JSON、前后说明文字和尾随噪声；纯文本时追加一次有界纠正请求。模型请求硬上限仍为 5 次（主管 2 + 发现 2 + 汇总 1），委派后的实际请求数写入 `source.model_requests`。
- Worker 失败摘要保留 `LLMRequestError` 的真实说明（如“决策不是有效 JSON”），不再一律折叠为“外部调用历史不确定”；未知异常仍使用保守摘要。
- 0010 部分唯一索引 `uq_messages_assistant_run_id` 允许同一 Run 同时关联一条用户消息和一条 assistant 消息，同时保证每个 Run 至多一条 assistant 回复。

## 2. 验证

| 检查 | 结果 |
| --- | --- |
| `uv run pytest -q` | **51 passed**；新增 4 项决策解析/纠正重试测试 |
| Ruff、compileall、Alembic check | 通过；`alembic check` 返回 `No new upgrade operations detected` |
| 真实 PostgreSQL 迁移 | 0009 → 0010 升级通过；0010 → 0009 降级后重新升级通过 |
| 真实两轮对话 | 同一显式 shopping task：第 1 轮“给学生买奖品”生成可读追问和 completed Run；第 2 轮“25 人，预算 200 元，买彩色铅笔”生成 REV 3 和新 Run |
| 真实 Worker + DeepSeek + MCP | 两轮 Run 均由独立 Worker 执行并 completed；第 2 轮 `delegated_discovery`、MCP 调用 1 次、`simulated=true`、`source.model_requests=4` |
| assistant 消息 | 两个 completed Run 各恰好 1 条 assistant 消息，正文与 Run 结果一致；失败/取消路径没有 assistant 消息 |
| 幂等 | 同 `client_turn_id` 同内容重试返回 200 和原 Run/原 assistant；同键改内容返回 409 |
| 跨账号 | 第二账号读取任务、Run、消息和结果均返回 404 |
| 网页两轮展示 | 真实 Chrome 152 登录后显示 4 条消息、REV 3、两个“已完成”Run；结果显示委派=是、MCP 调用 1 次、模拟商品标记 |
| 网页刷新 | 刷新后用户/助手消息、REV 3、两个 Run 和结果与刷新前一致 |
| 前端 | `npm run lint` 通过（保留 2 条已有 React effect warning）；`npm run build` 通过 |

第 2 轮 `shopping:search_products` 对当前关键词返回空候选。Agent 明确说明这是模拟数据空结果，没有编造商品或价格；这符合“空结果/模拟来源准确”的验收要求。

## 3. 失败边界与遗留风险

- 主 Agent 连续两次返回不可解析内容时，Run 会 failed，错误摘要为真实解析失败原因，且不写 assistant 消息；此时需要用户创建新的回合/Run 重试。外部调用本身仍不承诺 exactly-once。
- 图仍无 checkpointer；“待答人数问题”通过最近一条 assistant 消息和服务端条件推断关联，不是原图节点暂停/续跑。
- Alembic autogenerate 仍提示 `messages` 与 `runs` 循环外键排序警告；当前迁移与 `alembic check` 正常，后续可评估拆分约束。
- 013 保留账号在早前 014 验收中产生的失败/取消 Run 仍在库中；本轮为遵守“不删除 013 保留数据”未逐条清理。本轮新建的 10 个隔离账号及 1 个空的历史测试账号已删除。

## 4. 清理与数据

本轮验收创建了隔离账号 `retest014a_*` / `retest014b_*`，完成 REST、Worker、浏览器和数据库校验后已删除；`accept014owner2`（无对话、无 Run 的早前测试账号）一并删除。013 的三个保留账号、对话、任务和 Run 未删除，数据库卷保留。API、Worker、Vite、Chrome 和 shopping-mcp 进程已停止。

## 5. 结论

014 的两轮多轮对话、条件修订、Run 绑定、真实 Worker/DeepSeek/MCP 执行、assistant 消息唯一持久化、幂等、跨账号隔离和浏览器刷新重读均已通过。014 可标记为**已完成**；完整采买方案、候选表、金额复算和 P3 规划仍不在本任务范围。
