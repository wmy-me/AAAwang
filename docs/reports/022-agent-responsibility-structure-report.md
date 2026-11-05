# 022 Agent 职责与包结构整理报告

## 状态

已完成。

代码职责入口已接入 Worker 生产路径，协调 Agent 现在拥有领域提示词、模型输出解析和能力可见性校验；Worker 保留 Run 生命周期、租约、取消、fencing、终态事务和分派。真实 DeepSeek、独立 Worker、PostgreSQL、高德 MCP 与 Java shopping-mcp 已完成直答、追问、地图、商品、组合和动态表单回归，浏览器刷新与权限隔离也已验证。

- 本轮起始 HEAD：`7083eaa`，前一轮 `7083eaa` 的职责入口改动保留并继续整理
- 起始工作区：干净
- 本轮未新增数据库字段、迁移、凭据或外部写操作

## 职责迁移

| 责任 | 022 入口 | 实际保留实现 | Worker 责任 |
| --- | --- | --- | --- |
| 结构化能力决策、直答/追问路由 | `agents/coordinator/service.py` | 协调 Agent 持有提示词、JSON 解析、纠正重试、地图位置校验和 `list_tools()` 可见集复核 | 领取 Run、租约、取消、fencing、终态事务、分派 |
| 商品信息发现 | `agents/discovery/service.py` | 复用唯一的 `agents/shopping.py` 有界 LangGraph 与 `run_tool_loop`，并在 discovery 入口提供商品提示词 | 只负责执行生命周期和结果提交 |
| 采买候选到方案 | `agents/procurement/service.py` | 唯一的 `modules/shopping_plans/service.py` 确定性规范化、金额/数量复算和方案校验；商品与组合路径都经此入口 | 保存已校验结果 |
| MCP 传输与发现 | `tools/mcp/`、`modules/capabilities/` | 未移动；继续负责通用协议和受信可见集 | 执行前重新发现并复核能力 |
| 出行 | `agents/travel/` | 仍是预留说明，没有伪造子图 | 不创建出行 Run |

没有新增第二个购物图、预算对象或能力注册表。`agents/shopping.py` 保留为兼容实现入口；生产 Worker 通过 `coordinator`、`discovery` 和 `procurement` 包的公开入口调用它。

## 新旧执行路径

旧路径：

```text
worker.run_once
  -> (旧) worker._run_capability_decision / (旧) worker._run_shopping_agent_with_lease
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

`worker/runner.py` 中原来的 `_run_capability_decision_impl`、`_decision_json`、纠正判断和 `_discover_capability_tools` 已移入协调 Agent；Worker 不再保存领域提示词或模型解析实现，也没有第二套决策逻辑。`RunBudget` 由 Worker 创建并原样传入 coordinator/discovery；本轮没有增加模型请求、委派、MCP 或远程调用。

## 安全与幂等

本轮只调整 Python 包入口，不新增字段或写操作。任务、消息、表单和 Run 继续按 owner、task、revision 查询；Run 继续由租约/fencing 和状态前提保护。模型不能提供用户身份、MCP URL、服务 ID、金额或权限；商品方案仍由确定性服务复算。外部 MCP 仍为只读，不声称 exactly-once。

## Java 服务排查与修复

前台命令：

```bash
cd mcp-services
timeout 60s ./mvnw -B -ntp -pl shopping-mcp spring-boot:run
```

结果：退出码 `124` 是命令超时终止，不是应用异常；日志显示 Tomcat 在 `127.0.0.1:8101` 启动、Registered tools: 1、无异常，随后由超时发送的终止信号触发 graceful shutdown。启动前 `8101` 无监听，`application.yml` 实际配置为 `server.address=127.0.0.1`、`server.port=8101`，未改端口。

根因：上一轮调试会话把 `spring-boot:run` 作为临时终端/调试会话的子进程；会话结束时子进程收到终止信号并优雅退出，造成“启动后退出”。不是端口冲突或应用启动失败。

最小修复：长驻联调使用 detached 启动，保留 8101：

```bash
cd mcp-services
setsid nohup ./mvnw -B -ntp -pl shopping-mcp spring-boot:run \
  > /tmp/shopping-mcp.log 2>&1 < /dev/null &
```

服务稳定后实际验证：

- 健康：`GET /actuator/health` 返回 `{"groups":["liveness","readiness"],"status":"UP"}`。
- MCP 初始化：协议版本 `2025-11-25`，服务名 `shopping-mcp`，版本 `0.1.0`。
- `list_tools`：发现 `shopping:search_products`，要求 `keyword`。
- `search_products`：`keyword=彩色铅笔` 返回 `source_type=mock`、`source_service=shopping-mcp` 和模拟候选；工具真实可调用，而不只是进程健康。

## 替身与本地验证

- 新职责入口、购物图、工具循环、能力 Worker、方案服务专项：`45 passed`
- 后端全量：`136 passed`
- Ruff、`python -m compileall -q src scripts tests`、Alembic check 通过；仅有既有 `messages`/`runs` 外键循环排序警告，无新迁移操作
- 前端 lint/build 通过；保留既有 3 条 React Hook warning
- 本轮重新执行 `./mvnw -B -ntp verify`：BUILD SUCCESS，shopping-mcp 6 个测试通过，travel/local-life 构建成功
- 结构测试确认 coordinator 拥有提示词/JSON 解析，Worker 不再保留旧决策实现；discovery 仍只有一条购物图；procurement 金额复算确定

## 真实验证

使用修改后的生产入口、真实 DeepSeek、独立 Worker、项目 PostgreSQL、高德 MCP 与 Java shopping-mcp：

| 场景 | Run | 结果 |
| --- | --- | --- |
| 直答 | `4aa6df1f-3a8e-46d1-bdbf-1046241c8e07` | `completed/direct_answer`；`model_requests=2`、`remote_calls=2` |
| 缺城市追问 | `c6c5562f-0bb2-4158-a598-57132e132565` | `completed/direct_answer`；`clarification` 可读，`model_requests=1` |
| 只查地点 | `1e2f23c7-da5f-48bd-be6b-b8121fbc9dda` | `completed/map_places`；高德返回 20 个地点，`mcp_attempts=1` |
| 只查商品 | `1461a434-13dd-4bac-9d28-6c848db37811` | `completed/shopping_agent`；3 个候选，`plan_status=valid`，`model_requests=5`、`delegations=1`、`mcp_attempts=1` |
| 商品+地图 | `cc4d61f1-da35-48c1-8795-da8c66fc596a` | `completed/capability_router`；20 个地点、1 个候选、`plan_status=valid`；共享预算 `model_requests=4`、`delegations=1`、`mcp_attempts=2`、`remote_calls=6` |
| 表单确认后方案 | `6410c52f-d97c-4e52-a251-7eaf5a79d0b0` | 原 goal 保留；`shopping_agent`，2 个候选、`plan_status=valid`；条件合并为 item/people/budget/quantity |
| 无预算探索 | `366e8358-b118-47f7-a10c-c3d48366635c` | `completed/direct_answer`；任务条件仍为 `{}` |
| 双账号隔离 | — | 第二账号读取组合 Run、结果、地点、商品制品均 404 |

浏览器使用 Playwright 无头 Chromium 登录账号 `cap022wdff41d`，任务 `e088425e-d2ba-438b-aa91-73efd76bff6a`、Run `b929ad2e-f943-422c-9c3d-2a8f6d87a48b`：刷新前后均显示商品计划、能力快照和条件，无错误提示。

## 边界与后续

- 浏览器验证为无头 Chromium，未执行有头人工交互。
- shopping-mcp 长驻依赖 detached 启动；这是运行方式修复，不修改端口或业务实现。
- 本轮不修改 Java 业务代码，不新增数据库迁移，不改变公开 REST 响应；搜索、天气、投稿和出行仍属于后续任务。
