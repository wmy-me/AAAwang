# 010 购物任务 Run 接入有限模型与 MCP 查询报告

## 状态

**已完成。** 2026-11-03 在真实 DeepSeek `deepseek-flash`、真实 Java `shopping-mcp` 和隔离 PostgreSQL 17 环境下完成三项验收：

1. 真实 DeepSeek 普通文本调用。
2. 真实 DeepSeek → shopping-mcp → PostgreSQL 购物 Run 闭环。
3. 真实外部调用已发生、数据库尚未提交时强制中断 Worker，并由新 Worker 接管恢复。

外部调用**不承诺 exactly-once**。中断实验中第一次尝试的 2 次模型请求和 1 次 MCP 调用已经发生，但结果没有写入数据库；恢复 Worker 重新执行了外部调用。数据库只保留最终一条结果。

## 实现

- 新增 `runs.execution_type`，旧数据和旧创建请求默认为 `diagnostic`；只有明确提交 `shopping_research` 且任务域为 `shopping` 时才进入购物执行路径，travel 会被拒绝。
- 新增 `shopping_run_results` 表和私有 `GET /api/runs/{run_id}/result`，结果保存受限回答、shopping 服务、实际工具名、模拟标志、受限工具结果、调用次数和 `010-v1` 执行版本。
- Worker 购物路径复用已有 `run_tool_loop`，固定服务 `shopping`、允许工具 `search_products`，客户端不能提交 URL、工具名或自由代码；条件上下文明确列出未知字段，不猜测缺失预算、物品或数量。
- 购物模型/MCP 调用期间使用独立数据库心跳续租；终态提交继续检查 worker、fencing token 和租约。续租或持有权丢失时不提交结果，并以需要新幂等键人工重试的安全失败收口。
- 结果写入与 Run 终态在同一数据库事务中完成；外部调用不承诺 exactly-once，也不自动无限重放不确定历史。

## 自动与替身验证

- `tests/test_runs.py`：9 项通过，覆盖购物执行类型、执行类型幂等冲突、travel 拒绝、结果接口私有性、旧 Run 版本快照和 fencing。
- `tests/test_tool_loop.py`：既有工具循环测试通过，工具白名单和受限调用仍保持原行为。
- 最终 Python 全量回归：**44 passed**；Ruff、compileall、`uv lock --check` 和 `git diff --check` 通过。
- Java `shopping-mcp` 及父模块构建：6 项测试通过，Maven `BUILD SUCCESS`。
- 替身测试只覆盖边界，不作为真实外部闭环证据。

## 真实外部验收环境

| 项 | 实际值 |
| --- | --- |
| 数据库 | 隔离 `postgres:17` 容器，宿主端口 `127.0.0.1:55440`，临时命名卷 |
| 迁移 | 从空库升级到 `20261103_0007 (head)`；重复升级无操作；`alembic check` 无新迁移 |
| MCP | 真实 Java `shopping-mcp`，`http://127.0.0.1:8101/mcp`，协议 `2025-11-25` |
| API | 真实 Uvicorn，`127.0.0.1:18010`，使用同一隔离数据库 |
| Worker | `python -m life_agent.worker.runner`，真实 DeepSeek 与真实 MCP |
| 模型 | DeepSeek `deepseek-flash`；密钥只从本地 `.env` 读取，未输出、未提交 |
| 清理 | 验收后停止 API 与 shopping-mcp，删除临时容器、网络和数据卷 |

## A. 真实 DeepSeek 调用

```bash
cd backend
uv run python scripts/check_llm.py
```

实际结果：

- 供应商 `deepseek`，模型 `deepseek-flash`
- 状态成功，耗时 `0.60 秒`
- 回复：“已收到测试请求。”
- Token：输入 15，输出 5，合计 20
- 退出码 0

## B. 真实 DeepSeek → shopping-mcp → PostgreSQL 闭环

通过真实 HTTP API 创建用户、私有对话和 shopping 任务，条件为：

```json
{"budget": 15.0, "people": 1, "item": "彩色铅笔", "quantity": 1}
```

再以 `execution_type=shopping_research` 创建 run。真实 Worker 以 `--once` 执行，命令耗时 `4.95 秒`。

实际结果：

- Run：`completed`，`attempt=1`，`fencing_token=1`，执行类型 `shopping_research`
- 最终回答摘要：“以下为模拟查询结果，商品和价格均为模拟信息……候选商品：彩色铅笔套装；模拟单价：12.8 元；单位：12支/盒。”
- 持久化来源：`service_id=shopping`，`tool=shopping:search_products`，`simulated=true`，`model_requests=2`，`tool_calls=1`，`execution_version=010-v1`
- 数据库：1 条 run、1 条 `shopping_run_results` 结果
- 事件：`run.queued:1 → run.running:2 → run.completed:3`
- SSE：`/api/runs/{id}/events/stream` 返回 `200 text/event-stream`，可补读全部三个事件
- 私有性：第二个登录用户读取该 run、结果和事件均返回 `404`

## C. 真实外部调用后进程中断与恢复

在隔离数据库中为同一任务、同一 revision 创建第二个 run，使用新的幂等键。临时 Worker harness 包装 `run_tool_loop`：真实 DeepSeek 与 MCP 调用完成后写入标记并暂停，确保此时数据库尚未提交结果。

中断前证据：

- 标记：`EXTERNAL_CALLS_DONE model_requests=2 tool_calls=1`
- Run：`running`，`attempt=1`，`fencing_token=1`，租约未过期
- 结果表：`0` 行
- 事件：`run.queued:1 → run.running:2`
- Worker 进程仍存活

随后对 Worker 发送 `SIGKILL`。租约过期后，恢复 Worker 领取该 run：

- 恢复命令耗时 `4.36 秒`
- 最终 Run：`completed`，`attempt=2`，`fencing_token=2`
- 最终结果表：仍只有 `1` 行
- 最终事件：`run.queued:1 → run.running:2 → run.running:3 → run.completed:4`
- 通过 `after=3` 读取：只返回 `run.completed`；SSE 重连同样只返回终态事件
- shopping-mcp 日志共记录 3 次 MCP 会话初始化：闭环测试 1 次、中断前 1 次、恢复 1 次

外部调用计数：

| 阶段 | DeepSeek 请求 | MCP 调用 | 数据库结果 |
| --- | --- | --- | --- |
| A 普通文本检查 | 1 | 0 | 不涉及 |
| B 完整闭环 | 2 | 1 | 1 |
| C 第一次尝试（被 SIGKILL） | 2 | 1 | 0 |
| C 恢复尝试 | 2 | 1 | 1 |
| **合计** | **7** | **3** | **2（两次完成的 run 各 1 条）** |

结论：

- 第一次尝试的真实外部调用已经发生且无法回滚，因此不能承诺 exactly-once。
- 恢复 Worker 重新执行了模型和 MCP 调用；数据库最终只有一条结果，没有重复结果行。
- 被杀死 Worker 没有恢复执行，因此本轮没有重复验证“迟到完成被 fencing 拒绝”；该场景仍由 009 的真实 PostgreSQL 回归覆盖。
- 本轮不保存第二次及之后模型请求的 token 用量，只记录请求次数；脚本 A 的 20 tokens 是唯一直接记录的成功用量。

## 未验证与边界

- 外部调用不提供 exactly-once；进程崩溃、网络超时或响应丢失后可能产生重复付费调用，需用新 run/幂等键人工重试。
- 购物 Run 回答仅是有限查询结果，不是完整 Agent、规划组合、预算硬校验、网页聊天、真实商品来源或订单。
- 未实现 LangGraph、多 Agent、意图路由、RAG、网页对话、订单或支付。
- 临时验收环境已清理；未写入密钥、认证头或真实 `.env`，未把测试密码写入仓库。
- 本轮未新增公开删除接口；删除链语义保持 009 的验收结果。
