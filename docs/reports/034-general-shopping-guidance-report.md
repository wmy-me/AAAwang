# 034 通用采购指导与场景解耦报告

- 日期：2026-11-06
- 基线：`59425a0`（本地 `main` 与 `origin/main` 同步）
- 范围：只完成 034；保留 031 的现有接入，未下载 Embedding 模型、未运行 `uv sync`、未启动备用 Compose，也未开始 035。

## 实现

- 删除 `backend/src/life_agent/skills/teacher_rewards.md`，新增无触发词的 `shopping_guidance.md`。其中只保留可复用的商品比较、来源区分、缺失条件、只读工具和不得交易边界。
- `agents/discovery/graph.py` 与 `agents/discovery/service.py` 直接装载该通用指导，不再将用户消息、条件或教师/学生/奖品词交给场景 Skill 选择。`skills/loader.py` 的 `shopping_guidance()` 是固定的可信提示资产读取，不是运行时分类器。
- 清除能力路由与旧聊天辅助判断中“奖品”“彩色铅笔”的专用商品触发词；商品意图仍由通用购买、商品、预算、数量、候选、采购等语言和既有模型意图层判断。discovery 生成查询关键词的示例也改为普通物品。
- 沿用唯一的 discovery 图、既有 Worker、RunBudget、动态 MCP 发现和工具白名单。未新增数据模型、会话字段、Agent 图、工具服务或固定调用顺序。模型可在现有可见工具和共享预算边界中选择直接回答、澄清、商品查询或在明确位置需要时的地图查询；商品候选与地点结果仍不可相互推断库存或价格。

## 数据、安全与幂等

本任务不写入新业务数据、不新增字段、密钥或外部服务调用；现有 owner、Run、租约、取消、共享预算和只读工具约束保持原样。因此没有新的个人数据、幂等键或外部副作用需要引入。普通聊天的意图校验仍返回 `chat`，不会因为本任务的提示资产选择商品或地图工具。

## 精简验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 两个自然语言采购示例 | 通过（替身） | `test_general_shopping_guidance.py` 检查“给学生买奖品（有预算）”和“推荐适合通勤的水杯（无预算）”均加载 `shopping_guidance`，均不含 `teacher_rewards`。 |
| 无预算与普通聊天 | 通过（替身） | 同一检查确认提示允许探索或必要追问；`chat` 意图校验不选任务或外部工具。 |
| 既有商品 Agent 委派 | 通过（FakeModel/FakeMCP） | `test_delegation_uses_only_discovery_tool_and_persists_source_facts` 的受控事件循环执行成功，仍只调用允许的 `shopping:search_products`，且 supervisor 提示含 `shopping_guidance`、不含 `teacher_rewards`。 |
| 静态检查 | 通过 | `PYTHONPATH=src .venv/bin/python -m compileall -q src/life_agent tests/test_agent_prompt_skills.py tests/test_general_shopping_guidance.py tests/test_shopping_agent.py` 与 `git diff --check` 均为零失败。 |

当前虚拟环境没有 `pytest`；按照本任务“少量必要检查”和“不运行 uv sync”的限制，未安装依赖或运行全量套件。直接以标准 `asyncio.run` 调用既有商品 Agent 检查时，在执行断言后等待事件循环关闭超过 12 秒；使用有界受控事件循环执行相同 FakeModel/FakeMCP 断言通过。此现象未触发真实服务、未影响本任务的提示资产结论，未在 034 范围内扩展修复。

## 未运行的项目

- 未进行真实 DeepSeek、商品 MCP、高德 MCP、PostgreSQL、Worker、浏览器或 SSE 冒烟；034 文档将其列为“服务正常时可选”的检查，不能由上述替身结果替代。
- 未运行 BGE-M3、Mem0 + pgvector 或 031 真实联调；它们继续按既有 031 报告为待验证状态。

## 结论

034 的实现与规定的精简替身验收已完成：教师奖品不再是运行时专用 Skill/关键词路径，采购指导为通用提示资产，现有执行链和安全边界保持不变。真实外部服务闭环未执行且未标记为已通过。
