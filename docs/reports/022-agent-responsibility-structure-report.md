# 022 Agent 职责与包结构整理报告

## 状态

部分完成，真实组合回归受阻。

代码职责入口已建立并接入 Worker 生产路径，旧 Run、消息、表单、能力白名单和共享预算契约保持不变。真实 PostgreSQL、DeepSeek、API 和独立 Worker 的 coordinator 直答路径已验证；shopping-mcp 本轮未能保持启动，真实商品/地图组合路径未验收，因此不将 022 标记为完成。

- 起始 HEAD：`cf02a416e1d6bd56be5b13882bbe140dc085ec91`
- 起始工作区：干净
- 本轮未新增数据库字段、迁移、凭据或外部写操作

## 职责迁移

| 责任 | 022 入口 | 实际保留实现 | Worker 责任 |
| --- | --- | --- | --- |
| 结构化能力决策、直答/追问路由 | `agents/coordinator/service.py` | 通过兼容适配调用现有受限决策实现；模型选择仍由后端可见能力集合约束 | 领取 Run、租约、取消、fencing、终态事务 |
| 商品信息发现 | `agents/discovery/service.py` | 复用唯一的 `agents/shopping.py` 有界 LangGraph 与 `run_tool_loop` | 只负责执行生命周期和结果提交 |
| 采买候选到方案 | `agents/procurement/service.py` | 唯一的 `modules/shopping_plans/service.py` 确定性规范化、金额/数量复算和方案校验 | 保存已校验结果 |
| MCP 传输与发现 | `tools/mcp/`、`modules/capabilities/` | 未移动；继续负责通用协议和受信可见集 | 执行前重新发现并复核能力 |
| 出行 | `agents/travel/` | 仍是预留说明，没有伪造子图 | 不创建出行 Run |

没有新增第二个购物图、预算对象或能力注册表。`agents/shopping.py` 保留为兼容实现入口；生产 Worker 通过 `coordinator`、`discovery` 和 `procurement` 包的公开入口调用它。

## 新旧执行路径

旧路径：

```text
worker.run_once
  -> worker._run_capability_decision
  -> worker._run_shopping_agent_with_lease
  -> agents.shopping.run_shopping_agent
  -> modules.shopping_plans.service.build_artifacts
```

新路径：

```text
worker.run_once
  -> agents.coordinator.decide_capabilities
  -> worker lease wrapper
  -> agents.discovery.run_product_discovery
  -> agents.procurement.build_validated_plan
  -> modules.shopping_plans.service
```

旧 `_run_capability_decision` 仍保留为内部兼容适配，旧测试和调用方不需要同时维护另一套决策逻辑。`RunBudget` 由 Worker 创建并原样传入 coordinator/discovery；本轮没有增加模型请求、委派、MCP 或远程调用。

## 安全与幂等

本轮只调整 Python 包入口，不新增字段或写操作。任务、消息、表单和 Run 继续按 owner、task、revision 查询；Run 继续由租约/fencing 和状态前提保护。模型不能提供用户身份、MCP URL、服务 ID、金额或权限；商品方案仍由确定性服务复算。外部 MCP 仍为只读，不声称 exactly-once。

## 替身与本地验证

- 新职责入口、旧购物图、工具循环、能力 Worker、方案服务：`35 passed`
- 后端全量：`136 passed`
- Ruff：通过
- `python -m compileall -q src tests`：通过
- Alembic check：通过；仅有既有 `messages`/`runs` 外键循环排序警告，无新迁移操作
- 前端 lint/build：通过；保留既有 3 条 React Hook warning
- 结构测试覆盖 coordinator 兼容边界、discovery 单一图转发、procurement 确定性金额复算

## 真实验证

本轮启动了 API，并使用真实项目 PostgreSQL、真实 DeepSeek、HTTP 认证、任务/消息/Run API 和单次独立 Worker 创建并完成一条 coordinator 直答 Run。临时用户在验证结束后删除，未输出密钥。

结果摘要：

- `run_status=completed`
- `execution_type=direct_answer`
- `decision_kind=direct`
- `model_requests=2`
- `delegations=0`
- `mcp_attempts=0`
- `remote_calls=2`
- 真实配置显示 DeepSeek、地图和 shopping MCP 均启用，但 shopping MCP 服务本轮未保持运行

shopping-mcp 的 Java 调试会话曾报告启动成功，但随后会话结束；检查 `8101` 和 `8080` 均不可访问，当前没有活动 Java 调试会话。由于启动故障未被定位，未使用原始 `java`/Maven 绕过调试规则，也没有把历史 020 组合 Run 当作本轮新入口证据。

因此以下验收本轮未完成：

- 真实 DeepSeek + shopping-mcp + 高德 MCP 的商品/地点组合
- 真实 discovery 入口返回商品来源与模拟标记
- 真实采购方案落库的 022 新入口组合
- 真实浏览器回归

## 剩余风险与后续

1. 需要先诊断并恢复 shopping-mcp 的独立启动，再用新 discovery/procurement 入口重跑至少一条商品或地图+商品组合。
2. 浏览器自动化工具当前不可用，本轮没有把 HTTP 真实验证扩大为浏览器证据。
3. 当前 coordinator/discovery 入口是职责边界和兼容适配层；后续若要彻底把提示词/决策解析从 `worker/runner.py` 移出，应另建小任务并保持本报告中的预算与契约不变。

本轮不修改 Java 代码，不新增数据库迁移，不改变公开 REST 响应。
