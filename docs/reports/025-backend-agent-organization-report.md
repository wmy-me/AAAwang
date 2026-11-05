# 025 后端 Agent、Skill 与 Tools 结构整理报告

## 结论

025 已完成。当前结构按实际职责收敛，没有为了目录外观重排整个后端，也没有新增数据库字段、迁移、预算对象或 Agent 图。

本次核心改变是解除公共 Skill loader 对 discovery 私有目录的反向依赖，并合并两个只有单一职责的短 discovery 文件。生产行为和 024 已验证的能力保持兼容。

## 当前结构与调用链

### Agent

- `agents/coordinator/`：主协调入口、能力可见集、执行前 MCP 发现校验和 coordinator system prompt。
- `agents/discovery/service.py`：商品发现生产入口。
- `agents/discovery/graph.py`：唯一商品 discovery LangGraph；现在同时持有紧密相关的 `DiscoveryState` 和 `delegate_tool()`，避免 `state.py`/`nodes.py` 只有一个短定义。
- `agents/procurement/`：确定性候选校验、金额/数量和采买方案边界。
- `agents/shopping.py`：只保留旧导入兼容导出，不再包含第二套实现。
- `worker/runner.py`：只负责 Run 领取、租约、续租、取消、fencing、终态事务和能力分派。

生产商品调用链为：API 创建 Run -> Worker claim/lease -> coordinator 能力决策 -> discovery service -> 唯一 discovery graph -> `run_tool_loop` -> 受信 MCP 工具 -> PostgreSQL 终态结果。金额和数量仍由 procurement/服务端确定性计算，不交给 Skill 或模型决定。

### Skill 与提示词

- `life_agent/skills/loader.py`：SkillDefinition、注册、文件发现、唯一触发匹配和上下文渲染。
- `life_agent/skills/__init__.py`：稳定公共导出入口。
- `life_agent/skills/teacher_rewards.md`：`teacher_rewards` v1.0 场景资产。
- `agents/shared/prompt_loader.py`：可信 prompt 资产加载。
- `agents/shared/prompts/source_rules.md`：共享来源和未知信息规则。
- `agents/discovery/prompts/system.md`、`agents/coordinator/prompts/system.md`：各 Agent 角色提示。

Skill loader 现在只扫描自身顶层 Skill 根目录，不再通过 `agents/shared/skill_loader.py` 硬编码 `discovery/skills/`。新增 Skill 只需增加受信元数据文件或通过 `SkillDefinition` 注册，不需要修改 discovery graph 节点。Skill 仍不能授予工具、MCP、预算或身份权限。

### Tools

- `tools/mcp/`：通用 Streamable HTTP MCP 初始化、list_tools、schema、调用和错误分类。
- `tools/maps/`：地点与天气领域适配器，只使用配置允许的地图 MCP 工具。
- `tools/search/`、`tools/knowledge/`：预留扩展位置。
- `modules/capabilities/routing.py`：静态能力与实时 MCP 工具发现结果的交集、任务域和 schema 校验。
- `core/llm/tool_loop.py`：执行前工具暴露和调用期白名单控制。

工具层不承载 Agent prompt、场景 Skill、业务金额计算或 Run 租约。模型提供的 URL、service ID、tool name 不会直接进入授权路径。

## 代码改动

- 合并 `discovery/state.py` 到 `discovery/graph.py`。
- 合并 `discovery/nodes.py` 的 `delegate_tool()` 到 `discovery/graph.py`。
- 删除 `agents/shared/skill_loader.py`，新增顶层 `life_agent/skills/loader.py` 和稳定导出包。
- 将 `teacher_rewards.md` 从 `agents/discovery/skills/` 移至 `life_agent/skills/`。
- 更新 discovery、测试和维护 README 的导入路径与职责描述。
- 没有新增迁移；没有修改 Run、事件、结果、权限或预算契约。

## 自动化验证

- 核心 Agent/Skill/兼容测试：`16 passed`。
- 地图、天气、能力路由、Worker、工具循环专项：`59 passed`。
- 后端全量：`152 passed`。
- `uv run ruff check src tests`：通过。
- 旧路径残留检查：未发现 `agents.shared.skill_loader`、`discovery/skills`、`discovery.nodes` 或 `discovery.state` 引用。
- API、shopping-mcp、网页 HTTP 健康检查均为 `200`。
- DeepSeek、PostgreSQL、高德开关和数据库配置均已确认可用，未输出密钥。

## 真实商品 Run

- Run：`445a8f9a-b180-47b0-8229-18a9ead33c9c`
- 目标：给 25 名学生买彩色铅笔作为教师奖品。
- 链路：真实 DeepSeek -> 独立 Worker -> PostgreSQL -> 新 discovery graph -> Java `shopping-mcp`。
- 状态：`completed`；`shopping_product_discovery`；委派 1 次；MCP 1 次；模型 5 次；远端调用 5 次；预算未耗尽。
- 来源：`shopping:search_products`，`source_type: mock`，`simulated: true`，服务 `shopping-mcp`。
- 结果：返回学生奖品文具和奖励贴纸模拟候选；服务端完成 25 人、25 件、200 元条件下的方案校验。

Java shopping-mcp 是模拟商品服务，因此价格和库存仍明确标记为模拟，不代表真实商家数据。

## 浏览器验收

使用 `/usr/bin/google-chrome` 与临时 Playwright 环境：

- 账号：`agent025_browser_retry_1793857946966`。
- 创建教师奖品任务，填写商品、预算、人数和数量。
- Agent Run 完成，页面显示候选、模拟商品来源和结果。
- 刷新后任务、Run 状态、候选和模拟来源仍可读取。
- 第一次浏览器尝试因模型一次返回多个委派而被服务端拒绝，符合既有一次委派上限；该拒绝证明安全边界仍生效，重试后成功。

重试页面本次返回的是信息发现结果而非服务端采买方案，属于模型对条件/候选的受控响应；页面没有把模拟商品写成真实库存或真实下单。

## 地图与天气回归

本轮没有修改 `tools/maps`、能力路由或 Worker 天气分支。地图/天气/能力路由/Worker/工具循环专项测试 `59 passed`；023 已有的真实高德 MCP、DeepSeek、PostgreSQL、浏览器刷新和隔离证据继续有效，详见 [023 报告](023-amap-weather-mcp-report.md)。本轮不把 HTTP 健康检查冒充 MCP 或高德真实调用证据。

## 边界与限制

- `search/` 和 `knowledge/` 仍为预留目录，没有为了本任务创建空实现。
- Skill 使用服务端唯一触发匹配；没有唯一匹配时不加载。
- 商品 MCP 是模拟服务，暂无真实电商下单、支付或库存确认。
- 外部调用仍不承诺 exactly-once；既有 Run 幂等、租约和 fencing 语义未改变。

## 验收结论

Agent、Skill、Tools 结构、唯一生产图、权限边界、真实商品 Run、Chrome 查看/刷新和地图天气专项回归均通过。025 标记为已完成，并在此停止，不进入后续业务任务。
