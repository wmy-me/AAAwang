# 025：整理后端 Agent、Skill 与 Tools 结构

- 状态：待执行
- 前置：024 已完成；执行前核对最新提交和工作区。
- 报告：`docs/reports/025-backend-agent-organization-report.md`

## 目标

按用户要求用清晰、适度的结构组织 Agent、Skill、Tools。先梳理真实依赖和运行链，再调整生产代码。避免把每个 Agent 拆成过多薄文件，也避免用目录名掩盖职责混合。024 已验证的功能和行为保持兼容。

## 参考

GoGo 固定提交 `d7823df02887b01e31ffa094d06ab22653876098`：`agent/MasterAgent.java` 负责主 Agent 的模型、子 Agent 及工具注册；`agent/InfoAgent.java` 注册本地工具与允许的 MCP 工具；`agent/ItineraryPlanAgent.java` 注册 SkillBox；`agent/common/PromptLoader.java` 加载独立系统提示词。借鉴职责组织，不照搬 Java 框架或引入 shell 执行。

## 结构方向

围绕现有 `backend/src/life_agent/`：

- `agents/`：按 Agent 放协调与商品发现的实现入口、状态和必要的图逻辑；仅在文件职责或规模确有需要时拆分，避免只有一个短函数的薄模块。
- `skills/`：场景 Skill 定义、注册/选择和内容，按需加载；公共加载器不反向依赖某个 Agent 的私有目录。教师奖品 Skill 保留现有能力，未来新增 Skill 不需要改图节点。
- `tools/`：按业务和接入方式维护本地工具、地图适配器、MCP 客户端；Agent 根据后端授权范围注册和使用。
- 系统提示词作为独立资产维护，可使用公共 `prompts/` 或清晰的现有位置，Agent 通过稳定加载入口引用；不引入大量空目录。
- `modules/` 管业务数据与确定性计算，`worker/` 管 Run 领取、租约、取消、事务和执行调用，`core/` 管通用基础设施。按实际代码判断，不为外观强制重排全部项目。

024 中 `discovery/graph.py` 仍集中大量逻辑，`nodes.py` 只包含委派工具定义，`state.py` 很短；检查后将紧密相关内容适度合并，职责边界清晰的内容再独立。当前 `agents/shared/skill_loader.py` 直接指向 discovery 的 Skill 目录，应解除此反向依赖。保留旧导入兼容层仅限确有调用方需要，更新生产引用并避免双实现。

## 执行与验收

1. 先核对最新代码、024 报告，记录旧/新目录、实际调用链与导入映射；先检查 DeepSeek、PostgreSQL、Worker、shopping-mcp、高德与浏览器可用性。保持用户本地配置和已有数据。
2. 整理当前已实现的 Agent、Skill、Tools 与提示词位置，修正导入、资源加载与打包路径。保证模型在允许能力范围内作出选择；Skill、工具和 Graph 的执行次序不写死；白名单、共享预算、超时和用户隔离由服务端控制。
3. 自动化验证生产路径加载角色提示与教师奖品 Skill；普通商品不误加载；验证注册新 Skill 无需改 Agent 图代码、非法工具被拒、旧 Run 可读、共享预算和取消/失租保护。运行相关测试、后端测试与构建检查。重点测试实际行为，避免增加只检查文件布局的测试。
4. 完整执行一次真实 DeepSeek → 独立 Worker → Java 模拟商品 MCP → PostgreSQL 的商品任务，在浏览器查看并刷新结果；检查地图/天气路径回归。报告区分真实服务、模拟商品与受控测试。遇到可自行修复的问题应继续修复和复验，确有外部阻塞记录具体证据。
5. 更新 Agent/Skill/Tools 维护说明、进度、任务索引与报告。所有关键验收满足才标记完成；完成后停止，不自动进入后续业务阶段。
