# 019 购物主 Agent 受控能力路由与工具白名单报告

## 当前状态

已完成首版代码实现、替身回归和核心真实闭环验收。实现保留 018 的 `map_places`、`shopping_agent` 和旧地点 API；新增能力快照与组合 `capability_router` Run。

## 已实现

- 新增受信能力注册表：`shopping_product_discovery` 和 `map_place_search`，记录 Agent、任务域、服务 ID、工具白名单、只读属性和结果类型。
- 任务聊天使用结构化 `CapabilityDecision`，覆盖商品、地点、缺城市澄清和地图+商品组合；`DIRECT` 决策已定义，但聊天入口暂仍交给 `shopping_agent`，尚未实现无工具直答。不接受模型或客户端指定 URL、服务或工具。
- Run 增加 `capability_ids` JSON 快照，迁移为 `20261104_0015`。旧 Run 的空快照保持兼容。
- Worker claim 后再次检查注册能力、shopping 任务域、只读属性和允许的单能力/组合；未注册能力在执行前拒绝。
- 同一 task 幂等键重试必须匹配 revision、execution type 和能力快照。
- 组合请求使用单个 `capability_router` Run；地图和商品结果分别保留来源，地点不进入商品候选或金额计算。网页对组合 Run 同时读取商品 artifacts 和地点结果。
- 地图来源使用独立的 `map_source` 持久化，避免组合 Run 把地点行误标成 shopping 来源。
- 组合 Run 的商品分支复用既有 `shopping_agent` 主从图：路由已经选定商品发现后，跳过重复的主判断，直接走入发现节点，并要求发现模型执行一次受限工具调用；没有增加多轮规划或写工具。

## 替身验证

- 后端全量测试：`108 passed`；组合工具循环、能力路由、Worker 白名单和地图解析窄测试：`53 passed`。
- 能力路由、Worker 白名单、地图兼容路由和 Run 测试均通过。
- Ruff、compileall、`alembic check` 通过；本地 PostgreSQL 已应用 `20261104_0015`。
- 前端 lint/build 通过；保留已有 2 条 React Hook warning。

## 真实核心验收

- 已使用 `backend/.env` 中的真实 DeepSeek 和高德配置；高德 `maps_text_search` 返回真实地点，`simulated=false`。
- 已启动独立 Worker、真实 PostgreSQL 和本地 Java `shopping-mcp`；最新真实组合 Run 为 `9505745a-5c2a-4b31-99a4-04bda7f6b91c`，执行类型 `capability_router`，能力快照为 `map_place_search + shopping_product_discovery`，`mcp_call_count=2`、`model_requests=3`、`delegations=1`。
- 同一个 Run 已持久化 20 条高德地点、2 条 `shopping-mcp` 模拟商品候选和服务端校验方案；地图地点来源为 `map/maps_text_search`，商品来源为 `shopping/mock`（`source_service=shopping-mcp`、`simulated=true`），地点未进入商品候选或金额计算。
- 商品单能力、地图单能力、缺城市澄清和组合入口均有真实或替身验证；组合 Run 的城市与商品关键词已用“帮我看看上海附近的礼品店，并给25人购买奖品，预算200元”真实验证，刷新读取使用授权的 result、map-places 和 shopping-artifacts API。
- 已用第二个真实账号读取该 Run 的 run、result、map-places 和 shopping-artifacts，均返回 404；取消/失租、重复请求和版本冲突沿用 015–018 的 Run 机制，本轮未逐项重新执行浏览器回归。

## 尚未实现的架构增强

- 当前能力路由仍是受信服务端结构化规则，不是模型自主选择能力；模型级 schema 决策和真实共享预算尚未接入。
- 能力描述尚未包含输入 schema、独立超时和预算字段，当前使用全局配置与路由规则。
- 商品 Agent 仍使用既有有限主从路径；组合路径为控制预算跳过重复主判断并强制一次发现调用。发现工具循环仍受两次模型请求和一次 MCP 调用上限约束，另有一次汇总请求；本轮没有扩展多轮规划、长期记忆、任意 MCP 或写工具。

## 安全与边界

能力选择只产生后端注册 ID；远端返回内容不能增加权限。Key、认证 URL 和原始异常不进入 Run 或日志。外部只读调用不承诺 exactly-once；失败、空结果、取消、失租和旧版本不得伪造成功。