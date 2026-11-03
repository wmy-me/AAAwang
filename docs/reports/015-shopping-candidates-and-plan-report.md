# 015 教师奖品采买候选与结构化方案报告

验收日期：2026-11-03
状态：**已完成**

## 1. 实现范围

本轮为既有 shopping task 增加候选快照、服务端确定性方案复算、方案读取 API 和网页展示。0011 Alembic 迁移创建 `shopping_candidates`、`shopping_plans` 与 `shopping_plan_items`。候选保存 owner、task、revision、run、稳定 `product_id`、名称、Decimal 单价、币种、包装单位、可分份数、可用性、来源、报价时间、查询时间和 `simulated` 标记；同一 Run 的 product 使用唯一约束去重，方案按 Run 唯一保存。

Worker 在 `shopping_agent` 完成后将 MCP 证据白名单规范化，再由 `Decimal` 和 `ceil(people / distributable_units)` 计算有效方案。方案、候选、Run 结果、assistant 消息和终态事件在同一事务中写入；有效回答由服务端根据方案生成，避免模型自然语言的数量或金额覆盖结构化校验结果。整体 Agent 截止时间配置为 180 秒，既有主从图仍保持最多 5 次模型请求、1 次委派、1 次 MCP 业务调用的更紧上限。

新增 `GET /api/runs/{run_id}/shopping-artifacts`。服务端按 owner、task 和 Run 授权，越权统一 404；旧 revision 的 Run 和方案可继续读取，不能覆盖新 revision。

## 2. 真实端到端验收

隔离账号：`accept015prizes`；任务：教师为 25 名学生采购奖品，每人至少一份，总预算 200 元。保留用户数据，验收结束仅删除临时跨账号验证用户。

| 检查 | 结果 |
| --- | --- |
| PostgreSQL | 真实 0011 迁移已升级，候选/方案数据持久化并可刷新读取 |
| DeepSeek | 真实调用；有效 Run 记录 `model_requests=4` |
| Java MCP | 真实 `shopping-mcp` Streamable HTTP `/mcp`；健康端点 `UP`，业务调用 1 次 |
| Worker | 独立进程领取 Run，Run `attempt=1`、状态 `completed` |
| 候选快照 | 2 个实际 MCP 模拟候选：文具套装 ¥6.50、贴纸包 ¥6.90 |
| 服务端方案 | 贴纸包 1 包，覆盖 `25/25` 人，预算 ¥200.00，总额 ¥6.90，余量 ¥193.10 |
| 费用语义 | `unknown_fees=true`；明确运费、税费和优惠未计入，不代表最终成交价 |
| 网页刷新 | 刷新后恢复 REV 3、候选列表、服务端方案与金额 |

第一次真实 Run 曾因模型自然语言关键词与旧 MCP 完全匹配规则不兼容而得到空候选；修复为标签包含匹配后重新启动 MCP 验证成功。该第一次空结果 Run 保留为真实空结果历史证据。

## 3. 版本、失败和权限

- REV 2 将人数改为 30，但任务目标仍写“25 名学生”。模型识别到条件冲突，返回 clarification，Run completed 但没有候选和方案；这验证了条件冲突不会伪造规划结果。
- REV 3 将预算改为 180 元，人数仍为 25，生成独立候选快照和方案：总额 ¥6.90、余量 ¥173.10。旧 REV 1 仍可读取，网页切回旧 Run 显示 `VALIDATED PLAN / REV 1` 和原预算 ¥200.00。
- 新增自动化测试使用替身数据库验证终态事务、同一 claim 的迟到重放被 fencing 拒绝、候选/方案各只保存一份以及第二账号读取 artifacts 返回 404。
- 方案无法形成时保存候选但不保存有效 plan；空候选、预算不足、缺失人数和不合格候选在规划层返回无有效方案。取消、失租和 fencing 失败不会写入成功方案或 assistant 成功回复。

## 4. 验证结果

| 检查 | 结果 |
| --- | --- |
| `uv run pytest -q` | **57 passed** |
| 新增候选/方案测试 | Decimal 金额、覆盖人数、向上取整、重复候选、预算不足、服务端权威回答 |
| Run API 测试 | 终态候选/方案事务、迟到重放、幂等与跨账号权限通过 |
| Ruff、compileall | 通过 |
| Alembic check | 通过，无新增迁移漂移 |
| Java `./mvnw -B -ntp verify` | 6 项测试通过 |
| 前端 `npm run lint` | 通过，保留已有 2 条 React effect warning |
| 前端 `npm run build` | 通过 |
| 浏览器 | 登录、真实 Run、刷新重读、REV 1/REV 3 切换和候选/方案面板通过 |

## 5. 真实性边界与遗留风险

真实链路证明的是 DeepSeek 请求、Java 模拟 MCP、独立 Worker 和真实 PostgreSQL 的连接与持久化，不证明真实平台库存、报价、订单或 exactly-once。商品金额是服务端对模拟候选的复算；未知运费、税费和优惠没有被假定为零。当前方案是只读查询规划，不开放购物车、下单、支付或外部写操作。

主从图没有 LangGraph checkpointer；Run 租约、fencing 和终态事务保障的是数据库写入归属，不是图节点级断点续跑。更广泛的空候选、预算不足和工具失败边界由替身测试覆盖，真实外部失败仍可能需要创建新幂等键重试。

## 6. 结论

015 的候选快照、服务端复算方案、真实 DeepSeek→Java 模拟 MCP→Worker→PostgreSQL 闭环、版本并存、权限控制、预算语义和网页刷新读取均已通过。P3 首条只读采买闭环可标记为**已完成**；真实平台接入和交易能力留待后续任务。
