# 024 Agent 结构、系统提示词与 Skill 分层报告

## 结论

024 已完成。商品发现 Agent 已从混合式 `agents/shopping.py` 拆出真实结构，并由生产 Run 使用新入口。旧模块只保留兼容导出，没有创建第二套图、工具白名单或预算对象。

本次没有新增数据库迁移，也没有改变 Run、事件、结果和预算契约。Worker 的领取、租约、续租、取消、fencing、终态事务和能力分派边界保持不变。

## 实际结构

- `agents/discovery/graph.py`：唯一真实商品发现 LangGraph，保留原有有限委派、工具调用、结果解析和停止语义。
- `agents/discovery/state.py`：图状态契约。
- `agents/discovery/nodes.py`：受限 discovery 委派工具和节点辅助逻辑。
- `agents/discovery/service.py`：生产商品发现入口。
- `agents/discovery/prompts/system.md`：商品发现 Agent v1 角色、职责、停止和边界。
- `agents/coordinator/prompts/system.md`：主协调 Agent v1 角色、授权和安全边界。
- `agents/shared/prompt_loader.py`：从可信项目路径加载提示资产；缺失或空文件抛出 `PromptAssetError`。
- `agents/shared/prompts/source_rules.md`：来源、模拟数据、未知信息和 Skill 权限规则。
- `agents/shared/skill_loader.py`：受限 `SkillDefinition` 注册、唯一触发匹配和上下文渲染。
- `life_agent/skills/teacher_rewards.md`：`teacher_rewards` v1.0，教师/学生/奖品/班级/学校场景指导。
- `agents/shopping.py`：兼容旧导入的导出层，不再包含图实现。

系统消息与用户/工具上下文通过 `run_tool_loop(system_prompt=...)` 和 `call_deepseek(system_prompt=...)` 分离。Skill 正文作为参考指导注入 system 资产组合，不能修改工具、MCP allowlist、预算、用户身份或系统安全规则。

## Skill 选择策略

本轮采用服务端受限注册选择，而不是让模型自由发明 Skill：

1. 注册项包含名称、版本、作用范围、触发词、指导正文和来源。
2. 目标文本命中唯一 Skill 的触发词时选择该 Skill。
3. 无匹配或多个 Skill 命中时不加载，避免歧义扩大权限。
4. 新 Skill 通过注册元数据扩展，不增加 Graph 节点分支。

测试覆盖了教师奖品匹配、普通商品/天气/闲聊不匹配、动态注册和恶意正文不扩大委派工具。生产测试还捕获了模型请求，确认教师奖品 Skill 名称实际出现在 graph 的 system message 中。

## 自动化证据

专项测试与相关回归：

- `tests/test_agent_prompt_skills.py`：提示资产、缺失资产、Skill 选择、注册扩展和工具边界。
- `tests/test_shopping_agent.py`：真实 graph 的教师奖品 Skill system message 注入和旧购物行为。
- 024 核心聚焦测试：`33 passed`。
- 后端全量：`152 passed`。
- `uv run ruff check src tests`：通过。
- `uv run python -m compileall -q src tests`：通过。
- 前端 `npm run build`：通过。
- 前端 `npm run lint`：通过但保留 3 条既有 Hook warning，均在 `src/App.tsx`，与本任务无关。
- API、shopping-mcp、前端健康检查：HTTP 200。

本轮生产结构没有数据库字段变化，因此未新增迁移。Alembic 状态保持既有版本；任务的数据库兼容性由全量测试和真实 Run 验证。

## 真实生产闭环

### 教师奖品

- Run：`86af3d2f-4952-45f4-98ef-388948aaf6f9`
- 目标：给 25 名学生买彩色铅笔作为教师奖品。
- 链路：真实 DeepSeek 结构化决策 -> 独立 Worker -> discovery graph -> Java `shopping-mcp` -> PostgreSQL Run/result/artifact 持久化。
- 状态：`completed`；能力：`shopping_product_discovery`；委派 1 次；MCP 1 次；模型 5 次；远端调用 5 次；预算未耗尽。
- 来源：`shopping:search_products`，`source_type: mock`，`simulated: true`，服务 `shopping-mcp`。
- 结果：服务端复算出奖励贴纸包覆盖 `25/25` 人，小计 `¥6.90`，预算 `¥200.00`，并明确运费、税费和优惠未知。
- Skill：教师奖品场景选择 `teacher_rewards` v1.0，并进入实际商品 discovery 模型请求的 system message。

### 普通商品

- Run：`3aefc72c-8d67-480a-ab7e-cb53dc978c81`
- 目标：买一盒彩色铅笔。
- 状态：`completed`；能力：`shopping_product_discovery`；委派 1 次；MCP 1 次；模型 5 次；远端调用 5 次；预算未耗尽。
- 结果：返回 1 个彩色铅笔套装候选，价格 `12.8 CNY`，并保留品牌、颜色数、配送和真实库存等未知字段。
- Skill：普通商品未匹配 `teacher_rewards`，没有默认加载教师奖品指导。

上述两个 Run 使用真实 DeepSeek、真实独立 Worker 和真实 PostgreSQL；商品服务是项目内 Java 模拟 MCP，因此商品价格和库存均明确标记为模拟，不能解释为真实商家报价。024 本轮没有重复宣称高德真实天气证据，023 的高德验收仍由 [023 报告](023-amap-weather-mcp-report.md)负责。

## 浏览器证据

使用 `/usr/bin/google-chrome` 和临时 Playwright 环境完成真实网页流程，未修改仓库依赖：

- 账号：`agent024_browser_1793849970275`。
- 创建教师奖品购物任务并填写 25 人、25 件、预算 200。
- 页面启动 Agent，显示完成状态、委派信息、模拟商品候选和服务端校验方案。
- 刷新后重新读取同一任务，结果、候选、预算、覆盖人数和方案仍在。
- 页面显示 `模拟商品数据`，没有将模拟报价写成真实下单或真实库存。

## 限制与边界

- `teacher_rewards` 当前是受限关键词选择，不是模型自主 Skill 规划；歧义时选择为空以保持安全。
- 商品 MCP 仍提供模拟商品数据，024 不实现真实电商下单、支付或库存确认。
- travel、RAG 和开放式通用多 Agent 规划不在本任务范围内。
- 前端既有 3 条 Hook lint warning 未修改；它们不影响本任务构建和商品流程。

## 验收结论

生产唯一图、提示资产分层、按需 Skill、工具权限边界、共享预算、真实商品 Run、浏览器查看/刷新、后端全量回归和前端构建均通过。024 标记为已完成，并在此停止，不启动 025 或其他后续任务。
