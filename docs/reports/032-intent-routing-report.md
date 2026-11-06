# 032 独立意图识别与主 Agent 入口报告

- 状态：已完成（031 真实记忆联调仍暂缓）
- 日期：2026-11-06
- 任务：[032](../vibe%20coding/032-intent-routing.md)

## 实现

- 新增 `backend/src/life_agent/modules/intent/service.py` 作为唯一实际对话意图入口。它接收当前消息、已由 owner 限定的有限会话历史和任务候选，使用一次受预算约束的 DeepSeek 结构化判断，再校验 intent、候选 task ID、记忆操作和必要澄清。
- Worker 的 `conversation_route` 现直接导入该入口。`coordinator.service.classify_conversation_turn` 仅保留兼容转发；能力发现和 `decide_capabilities` 仍留在 coordinator。没有新增 Worker、路由 Run、工具调用流程或商品/地图/天气的并行分类器。
- 意图层区分普通聊天、新任务、继续/修改既有任务、明确记忆操作和歧义。模型只能给出建议：任务候选、revision、owner、能力白名单、参数校验、共享预算和 Run 租约仍由既有服务端链路控制。
- 复合请求通过 `secondary_intent` 显式返回澄清，避免把“记忆管理加业务查询”等单 Run 不能安全同时完成的请求静默压成一个意图。模型不可用或输出非法时，安全回退只会给出 chat/task/澄清，绝不合成记忆写入或删除。
- 修复 031 删除边界：`forget` 只需要受校验的 `memory_category` 和 `memory_key`，不再要求 `memory_value`；服务端 owner filter 和“非唯一即澄清”约束保持不变。记忆仍默认关闭，服务不可用时普通对话继续，未启动真实 Mem0。

## 聚焦验证

使用项目现有 Python 3.12（未执行 `uv sync`、未下载模型）运行了以下替身/纯代码检查：

- `test_intent_routing.py`：普通聊天保持直接路径；模型识别“换一个”延续到既有候选任务；复合记忆+查询请求变为澄清；forget 无新值可通过、无标识则拒绝。结果：`intent-focused-tests-ok`。
- `test_user_preference_memory.py`：FakeMem0 覆盖 owner 隔离、保存/召回/更新/删除、删除后不召回、同一消息重试、敏感数据拒绝、预算耗尽和检索失败；删除调用已改为无 `memory_value`。结果：`memory-focused-tests-ok`。
- `compileall`（`src/life_agent` 与两项测试）及 `git diff --check` 通过；确认 Worker 导入新意图入口。

当前 `.venv` 没有 pytest/Ruff 开发依赖；本轮按任务边界未运行全量测试、浏览器、真实 DeepSeek 冒烟、真实 Mem0/pgvector、BGE-M3 下载或 031 数据库迁移。替身结果不代表这些外部链路通过。

## 数据与执行边界

本任务未新增持久字段、数据库迁移、外部服务、密钥或敏感日志。意图结果不含 owner 授权；现有 Run 的幂等键、预算预占、取消、fencing 和任务 revision 继续生效。031 Mem0 的真实模型/数据库联调保持待补，不是 032 的完成前置条件。
