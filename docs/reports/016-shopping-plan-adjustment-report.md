# 016 方案调整执行报告

验收日期：2026-11-03
状态：**不可变方案调整与真实外部/浏览器闭环已验收；目标文本与结构化条件冲突提示未实现，016 尚不能整体标记为完成**

## 1. 实现范围

- 新增 `20261103_0012`，创建不可变 `shopping_plan_adjustments` 与方案项表；不修改 015 的 `shopping_plans`。
- 手动调整按 owner、task、revision、完成 Run 和候选快照绑定，客户端只提交候选 ID 与包装数量。
- 服务端复算多商品小计、覆盖人数、总额和余量，拒绝重复候选、非法数量、伪造候选、不同币种、不可用候选和预算不足。
- 使用 `(task_id, client_request_id)` 与请求指纹实现幂等；任务行锁和 `expected_adjustment_version` 实现并发前提检查。
- 新增 `POST/GET /api/tasks/{task_id}/shopping-adjustments`；旧 `GET /api/runs/{run_id}/shopping-artifacts` 保持兼容。
- 网页候选选择、包装数量编辑、提交和历史版本展示已接入；金额仍以服务端返回为准。
- 验收中发现并修复保存后历史列表同时标记两个“当前”的前端状态问题；刷新前即可只保留新版本为当前。

## 2. 真实端到端环境与账号

本轮在项目真实服务上执行，未使用替身数据库或模拟 HTTP：

| 组件 | 实际状态 |
| --- | --- |
| PostgreSQL | 项目 Compose 实例，Alembic 当前 `20261103_0012 (head)`，`alembic check` 无新操作 |
| Python API | `uvicorn life_agent.main:app` 于 `127.0.0.1:8000`，OpenAPI 已包含 `/api/tasks/{task_id}/shopping-adjustments` |
| Worker | 独立 `python -m life_agent.worker.runner` 进程，真实领取并执行 Run |
| DeepSeek | 真实 `deepseek-flash` 请求 |
| Java MCP | 真实 `shopping-mcp` Streamable HTTP `/mcp`，`/actuator/health` 为 `UP` |
| 网页 | Vite `127.0.0.1:5173`，真实 Chromium 无头浏览器 |
| 隔离账号 | `accept016prizes`；跨账号探测账号 `accept016probe` |

隔离数据：对话 `e370b103-be71-486f-a8d0-3e627e5970ef`、任务 `cc44ae6b-4b00-42e9-ba02-cea22a22e547`。本轮保留该账号的验收数据作为证据，另外只创建了跨账号探测账号 `accept016probe`。

## 3. 真实 DeepSeek → MCP → Worker 闭环

| 检查 | 结果 |
| --- | --- |
| REV1 Run `887ca385-8e54-4835-8693-a8eeafea5892` | `completed`，`attempt=1`，`delegated_discovery` |
| 真实模型与 MCP | `model_requests=4`、`mcp_call_count=1`、服务 `shopping`、工具 `shopping:search_products`、`simulated=true` |
| 候选快照 | 2 个实际 MCP 模拟候选：学生奖品文具套装 ¥6.50/包（每包 1 份）、奖励贴纸包 ¥6.90/包（每包 25 份） |
| 自动方案 | 贴纸包 1 包，覆盖 25/25 人，预算 ¥200.00，总额 ¥6.90，余量 ¥193.10 |
| 未知费用 | `unknown_fees=true`，运费、税费与优惠未计入 |

## 4. 手动调整、幂等、并发与权限

| 场景 | 实际结果 |
| --- | --- |
| 多商品行调整 V1 | 文具套装 ×1 + 贴纸包 ×1：总额 ¥13.40，覆盖 26 人，余量 ¥186.60，服务端 `Decimal` 复算 |
| 同键同内容重试 | 返回原调整 `44a07bdf-83f9-4117-a350-617ccf936155`，版本仍为 1，未新增版本 |
| 同键异内容 | `409`，提示幂等键已用于其他调整请求 |
| 双请求并发提交 | 相同 `expected_adjustment_version=1` 的两个不同键实际得到 `201`（版本 2，贴纸包 ×3，总额 ¥20.70、覆盖 75 人）和 `409`（当前版本 2），只有一个成为当前版本 |
| 无效数量 0 | `422` |
| 伪造候选 ID | `404` |
| 重复候选 | `422` |
| 超出预算 | `422`（文具套装 ×100，超过预算） |
| 客户端提交价格字段 | `422`，请求模型拒绝额外字段 |
| 跨账号读取调整历史 | `404` |
| 跨账号读取 Run artifacts | `404` |
| 跨账号提交调整 | `404` |

## 5. 新 revision、历史与条件一致性

任务目标文本保持“教师为 25 名学生采购奖品，每人至少一份，总预算 200 元”，随后通过修订接口创建 REV2，结构化条件改为 `budget=180`、`people=25`。

| 检查 | 结果 |
| --- | --- |
| REV2 首次 Run `ffcf6405-6a51-40ea-bb4c-0f5e56f90bbd` | `completed`、1 次 MCP，但模型关键词与模拟目录不匹配，候选为空、方案为 `null`；保留为真实空结果 |
| REV2 新幂等键重试 `9a4d352f-ae07-468a-ab47-6164922ac5ed` | `completed`，`model_requests=4`、1 次 MCP、2 个候选；方案为 REV2、预算 ¥180.00、总额 ¥6.90、余量 ¥173.10 |
| 旧 Run 自动方案 | `GET /api/runs/{run1}/shopping-artifacts` 仍可读取 REV1、预算 ¥200.00、余量 ¥193.10，未被覆盖 |
| 旧 revision 提交调整 | `expected_revision=1` 在 REV2 后返回 `409` |
| 旧 Run 冒充新 revision | 旧 Run 配 `expected_revision=2` 返回 `404` |
| REV2 手动调整 V3 | 版本 3，`task_revision_id` 为 REV2，预算 ¥180.00、总额 ¥6.90、余量 ¥173.10 |
| 最终历史 | 版本 1/2 绑定 REV1，版本 3 绑定 REV2；仅版本 3 `is_current=true` |

### 未满足的 016 要求

016 第 3.4 条要求：目标文字与结构化条件明确矛盾时，界面展示冲突并让用户确认或修正目标描述，再启动新 Run，不能悄悄覆盖。本轮真实链路中，目标仍写“总预算 200 元”，REV2 结构化预算为 180 元，系统直接按 180 元生成方案，既没有冲突提示，也没有确认或修正目标描述的入口；现有任务接口也不支持修改 `goal`。因此该要求**未实现、未验收**，不能与已通过的手动调整混为一谈。

## 6. 网页真实验收

真实 Chromium 浏览器以 `accept016prizes` 登录：

| 检查 | 结果 |
| --- | --- |
| 候选项与自动方案 | 显示 2 个模拟候选、`VALIDATED PLAN / REV 2`、预算 ¥180.00、合计 ¥6.90、余量 ¥173.10 |
| 模拟与费用提示 | 页面标注“模拟商品”，并显示运费、税费与优惠未知 |
| 手动调整 | 取消默认贴纸包，选择文具套装 ×25，提交后服务端返回 V5：¥162.50，页面提示“已保存手动方案第 5 版” |
| 保存后当前标记 | 修复前 V4 保存后历史同时显示两个“当前”；修复后 V5 保存后仅一个“当前” |
| 刷新 | 会话、REV2 自动方案、候选和 V5 历史均恢复，仍只有一个“当前” |
| 旧 revision 切换 | 切到“第 1 版”Run 显示 `VALIDATED PLAN / REV 1`、预算 ¥200.00、合计 ¥6.90 |
| 浏览器错误 | 登录前匿名 `/api/me` 返回 2 次预期 `401`（React 开发模式重复 effect）；登录后无 4xx/5xx、无页面异常 |

## 7. 自动化与静态检查

| 检查 | 结果 |
| --- | --- |
| `uv run pytest -q` | **59 passed** |
| `uv run ruff check src scripts tests` | 通过 |
| `uv run python -m compileall -q src scripts tests` | 通过 |
| `uv run alembic check` | 无新升级操作 |
| `npm run lint` | 通过，保留既有 2 条 React effect warning |
| `npm run build` | 通过 |
| `./mvnw -B -ntp verify` | BUILD SUCCESS，三个 MCP 模块通过 |

## 8. 真实性边界与遗留风险

真实链路证明的是 DeepSeek 请求、Java 模拟 MCP、独立 Worker、真实 PostgreSQL 与浏览器的连接和持久化，不证明真实平台库存、报价、订单或 exactly-once。商品金额是服务端对模拟候选的复算，未知费用没有被假定为零。

REV2 第一次空候选是真实外部行为，不是替身测试；本轮使用新幂等键重试，未自动无限重放。旧 Run 的迟到完成仍不能覆盖当前手动版本。

**未完成项：** 目标文本与结构化条件的冲突提示、确认和修正路径（016 §3.4）。在该项实现并真实验收前，016 只能标记“手动调整与真实闭环已完成，条件一致性提示待补”。
