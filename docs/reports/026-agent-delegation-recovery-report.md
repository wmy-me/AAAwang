# 026 商品发现 Agent 委派决策有界纠错报告

## 结论

026 已完成。商品发现链路现在对主 Agent 的非法委派决策和 discovery MCP tool loop 的非法工具响应分别提供一次有界纠错。首次非法响应不执行委派或 MCP；纠正后仍不合法时明确失败，不静默选择第一项，也不扩大工具白名单、预算或调用次数。

本轮没有实现并行 Agent 或多工具执行。真实模型正常路径与受控 FakeModel 纠错证据分开记录。

## 实施内容

- `agents/discovery/graph.py`：主 Agent 对多个委派、未知委派和非法参数统一允许一次修正；修正消息保留原 assistant tool-call 协议和当前上下文，继续使用同一 `RunBudget`。
- `core/llm/tool_loop.py`：发现工具响应对多个 tool call、缺失必需工具调用和非法响应增加一次明确纠错；纠正后必须恰好一个已授权工具并通过 schema 校验。
- 首次错误只增加一次模型请求，不调用 MCP；MCP 仅在最终合法工具调用真正执行时预占和计数。
- 重复非法响应、预算耗尽和既有取消/租约/超时语义保持安全停止。

## 受控纠错证据

`tests/test_shopping_agent.py` 覆盖主 Agent 多委派、未知委派、非法参数和共享预算纠错。

`tests/test_tool_loop.py` 覆盖：

- 多个 tool call -> 一次纠错 -> 一个合法调用 -> 一次 MCP；
- 纠正后仍多个 tool call，零 MCP 并明确失败；
- force 模式缺少工具调用，纠正后仍缺失则明确失败；
- 原有未知工具、非法参数、预算和普通拒绝路径继续通过。

主 Agent 与工具循环专项合计 `22 passed`。后端全量 `156 passed`，`uv run ruff check src tests` 通过，`compileall` 通过。

## 真实商品 Run

- 真实 API/Worker 商品 Run：此前已完成的 `a4a1302f-fb2f-4339-af87-d355f4d7b130`，用于证明真实 DeepSeek、独立 Worker、PostgreSQL 和 Java 模拟 `shopping-mcp` 的正常链路。
- 本轮真实 Chrome 账号：`agent026_browser_retry_1793858976960`。
- 页面创建“给25名学生买彩色铅笔作为教师奖品”任务后运行完成；刷新后仍能读取同一 Run、候选和模拟来源。
- 刷新后的页面显示：已完成、MCP 1 次、模拟商品数据、候选与采买方案；未显示执行失败。
- 本次真实模型 Run 是正常真实路径证据，不声称真实模型自然触发了多委派纠错。多委派纠错由上面的受控 FakeModel 测试证明。

Java `shopping-mcp` 返回的是模拟商品数据，价格和库存不代表真实电商报价、库存或下单能力。

## 验收边界

保留一次委派和一次 MCP 工具调用上限；不支持并行工具调用。工具名称和参数仍由服务端实时发现、白名单和 schema 校验控制。没有新增 Run 数据格式、数据库迁移、用户权限或采买金额计算逻辑。026 完成后停止，不进入 027。
