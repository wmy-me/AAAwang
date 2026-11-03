# 012：购物主 Agent 与信息发现 Agent 的最小委派报告

- 执行日期：2026-11-03
- 起始 HEAD：`449e752`（`docs: plan task 012 shopping agent delegation`）
- 状态：**已完成**
- 范围：最小 LangGraph 主从委派、shopping_agent Run 类型、结果元数据和回归；不实现网页聊天或完整采买规划

## 1. 已实现

- 新增 `shopping_agent` 执行类型，仅允许 shopping task；保留 `diagnostic` 和 010 的 `shopping_research` 语义。
- 新增 LangGraph 图：`supervisor -> discovery -> finalize`。主 Agent 只获得有明确描述的 `delegate_shopping_discovery` 能力；直接回答和追问在 finalize 结束，不调用 MCP。
- discovery 节点复用已有 MCP 客户端和受限 `run_tool_loop`，固定后端服务 `shopping` 与 `search_products`，最多一次委派和一次 MCP 调用。
- 新增 `decision_type`、`delegated`、`mcp_call_count` 结果字段及 Alembic `20261103_0008`，旧结果字段保持兼容。
- Worker 复用已有租约续期、取消检查、fencing 和终态事务；新结果通过原私有结果接口读取。
- 修复开发指南 5.4 误插入的 Compose 表格行，恢复 `check_tasks.py` 命令。
- 修正开发指南与 backend README 的配置来源：后端只读取仓库根目录 `.env`，`LLM_API_KEY` 不再指向 `backend/.env`。
- 更新 Run 与事件 REST 契约，说明三类决策、来源、调用次数和安全边界。

## 2. 自动与替身验证

| 检查 | 结果 |
| --- | --- |
| 直接回答不调用 MCP | 通过替身测试 |
| 关键条件不足时追问不调用 MCP | 通过替身测试 |
| 自主委派路径 | 通过替身测试，实际图节点经过 supervisor、discovery、finalize |
| 工具权限 | 通过，discovery 仅暴露 `shopping:search_products` |
| MCP 调用上限 | 通过，复用既有一次工具调用限制 |
| 结果来源 | 通过，记录服务、工具、模拟标志、受限结构化结果和调用次数 |
| 旧 Run/API 回归 | 通过，原有 Run 测试继续通过 |
| Python 测试 | **47 passed** |
| Ruff、compileall、uv lock | 通过 |
| Alembic | 项目库已从 `20261103_0007` 升级到 `20261103_0008`，`alembic check` 通过 |

## 3. 真实 API/Worker/PostgreSQL 端到端验收

环境：

- 项目 PostgreSQL 17：`127.0.0.1:55432`，既有项目卷，迁移到 `20261103_0008 (head)`。
- 真实 API：`127.0.0.1:18012`，使用根目录 `.env` 的项目数据库连接。
- 真实 Worker：`python -m life_agent.worker.runner --once`，真实 DeepSeek 与真实 Java `shopping-mcp`（`127.0.0.1:8101`）。
- 测试前项目库为空（0 用户、0 Run）；验收结束后删除前缀为 `verify012` 的测试用户，Run/结果/事件随 ORM 级联清理。

### 3.1 完整链路

通过真实 REST API 创建测试用户、私有对话、shopping task 和 `shopping_agent` Run；Worker 领取后执行：

`supervisor -> discovery -> finalize`

实际结果：

| 项 | 实际值 |
| --- | --- |
| Run 状态 | `completed`，`attempt=1` |
| 决策 | `delegated_discovery` |
| 是否委派 | `delegated=true` |
| MCP 调用次数 | `1` |
| 模型请求次数 | `4`（supervisor 1 + discovery 2 + finalize 1） |
| 工具身份 | `shopping:search_products` |
| 模拟来源 | `simulated=true`，`source_service=shopping-mcp` |
| 结果版本 | `012-v1` |
| 数据库 | `shopping_run_results` 持久化成功；Run 终态与结果同事务提交 |
| 事件 | `run.queued -> run.running -> run.completed` |
| SSE | `/api/runs/{id}/events/stream` 返回 `200 text/event-stream`，终态补读完整并关闭 |

### 3.2 空结果与候选结果

- 第一条成功 Run 的模型委派关键词返回了空候选。最终回答明确写出“返回的商品候选是空的”“不是查询失败”，并声明模拟数据，没有编造商品或价格。
- 第二条成功 Run 在目标中明确要求委派关键词使用“彩色铅笔”；真实 MCP 返回 1 个候选，最终回答引用“彩色铅笔套装”、12.8 元、12支/盒，并明确标记模拟信息。
- 两条 Run 的结果都保存了结构化工具结果和来源；空结果没有被伪装成错误，非空结果没有丢失来源。
- 两条成功 Run 合计 8 次真实模型请求、2 次真实 MCP 调用。

### 3.3 用户隔离与持久化重读

- 使用新的登录客户端重读已完成 Run，状态、结果、决策元数据和事件均可读取，证明结果来自 PostgreSQL 而非进程内存。
- 第二个用户读取该 Run、结果和事件均返回 `404`。
- HTTP 结果接口返回 `decision_type`、`delegated`、`mcp_call_count`，与数据库记录一致。

### 3.4 缺少密钥的安全失败

首次 Worker 执行时根目录 `.env` 的 `LLM_API_KEY` 为空，Worker 在模型调用前安全失败，Run 进入 `failed`，没有结果行，也没有发生 MCP 调用。将本地已有密钥同步到根 `.env` 后，用新的幂等键创建新 Run 并重试成功。报告未输出或提交密钥。

## 4. 运行方式

配置根目录被忽略的 `.env`（包含 `DATABASE_URL` 和 `LLM_API_KEY`），启动项目 PostgreSQL、真实 `shopping-mcp`、API 和 Worker。创建 run 时使用：

```json
{
  "expected_revision": 1,
  "idempotency_key": "client-generated-key",
  "execution_type": "shopping_agent"
}
```

Worker 会按现有方式领取并执行；结果使用 `GET /api/runs/{run_id}/result` 读取。直接回答或追问的 `mcp_call_count` 为 0；委派最多一次、MCP 最多一次。外部调用不承诺 exactly-once，也不会无限重放不确定历史。

## 5. 已清理与边界

- 验收后停止临时 API 和 shopping-mcp；项目 PostgreSQL 容器、项目卷和用户其他容器均未删除。
- 删除隔离测试用户及其级联数据；项目库恢复为验收前的 0 用户、0 Run。
- 本轮没有新增数据库业务表，只给现有 `shopping_run_results` 增加决策元数据列。
- 未实现网页聊天、完整意图识别、候选/方案业务表、P3 奖品组合、RAG、出行规划或真实交易；这些仍按后续编号任务推进。
