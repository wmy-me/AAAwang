# 019 购物主 Agent 受控能力路由与工具白名单报告

## 当前状态

已完成首版代码实现和替身回归，真实 019 全链路尚未完成验收，不能将本任务标记为整体完成。实现保留 018 的 `map_places`、`shopping_agent` 和旧地点 API；新增能力快照与组合 `capability_router` Run。

## 已实现

- 新增受信能力注册表：`shopping_product_discovery` 和 `map_place_search`，记录 Agent、任务域、服务 ID、工具白名单、只读属性和结果类型。
- 任务聊天使用结构化 `CapabilityDecision`，覆盖商品、地点、缺城市澄清和地图+商品组合；`DIRECT` 决策已定义，但聊天入口暂仍交给 `shopping_agent`，尚未实现无工具直答。不接受模型或客户端指定 URL、服务或工具。
- Run 增加 `capability_ids` JSON 快照，迁移为 `20261104_0015`。旧 Run 的空快照保持兼容。
- Worker claim 后再次检查注册能力、shopping 任务域、只读属性和允许的单能力/组合；未注册能力在执行前拒绝。
- 同一 task 幂等键重试必须匹配 revision、execution type 和能力快照。
- 组合请求使用单个 `capability_router` Run；地图和商品结果分别保留来源，地点不进入商品候选或金额计算。网页对组合 Run 同时读取商品 artifacts 和地点结果。
- 地图来源使用独立的 `map_source` 持久化，避免组合 Run 把地点行误标成 shopping 来源。

## 替身验证

- 后端全量测试：`102 passed`。
- 能力路由、Worker 白名单、地图兼容路由和 Run 测试均通过。
- Ruff、compileall、`alembic check` 通过；本地 PostgreSQL 已应用 `20261104_0015`。
- 前端 lint/build 通过；保留已有 2 条 React Hook warning。

## 尚未完成的真实验收

- 尚未重新执行 DeepSeek、独立 Worker、真实 PostgreSQL 和浏览器下的 019 商品、地点、缺城市追问和组合四条链路。
- 尚未真实验证组合 Run 的商品候选/方案与地图地点同时刷新、跨账号隔离、取消/失租、重复请求和版本冲突。
- 当前能力路由仍是受信服务端结构化规则，不是模型自主选择能力；模型级 schema 决策和真实共享预算尚未接入。
- 能力描述尚未包含输入 schema、独立超时和预算字段，当前使用全局配置与路由规则。
- 商品 Agent 仍使用既有有限主从路径；本轮没有扩展多轮规划、长期记忆、任意 MCP 或写工具。

## 安全与边界

能力选择只产生后端注册 ID；远端返回内容不能增加权限。Key、认证 URL 和原始异常不进入 Run 或日志。外部只读调用不承诺 exactly-once；失败、空结果、取消、失租和旧版本不得伪造成功。