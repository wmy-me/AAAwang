# agents/

智能体层目录。024 将商品发现图、角色提示词和场景 Skill 分层，并接入生产路径；旧购物入口仅保留兼容导出，travel 仍为预留。

| 子目录 | 后续职责 |
| --- | --- |
| `coordinator/` | 受限主协调：结构化决策、能力可见集和执行前 MCP 发现校验；角色提示在 `prompts/system.md` |
| `discovery/` | 商品发现 `service.py`、唯一真实 `graph.py`、`state.py`/`nodes.py` 和角色提示；场景 Skill 位于 `skills/` |
| `procurement/` | 确定性候选校验、预算计算和采买方案边界 |
| `shared/` | 可信提示资产加载、共享来源规则和受限 Skill 注册/选择 |
| `travel/` | 出行规划子图：交通、酒店与每日行程安排 |

`discovery/graph.py` 是唯一商品 LangGraph 实现；`shopping.py` 只从这里兼容导出，不得再创建第二套购物图或预算对象。图没有检查点或长期记忆，不代表完整通用 Agent。天气能力不是 LangGraph 图，而是 coordinator 选择后的受控 Worker/MCP 路径。

## 提示词与 Skill 维护

- 角色提示词和共享规则只能从受信项目文件加载；缺失或空文件必须让 `PromptAssetError` 明确失败。
- 用户输入、工具结果和来源事实只能作为运行上下文传入，不能覆盖 system prompt。
- Skill 是场景参考指导，不是工具、MCP 服务或权限授予。通过 `SkillDefinition` 注册，使用受限触发词选择；没有唯一匹配时不加载。
- 新 Skill 应增加元数据和测试，不能通过 Skill 正文扩大工具白名单、预算、用户身份或数据访问范围。
- Worker 负责 Run 领取、租约、取消、fencing、事务和分派；Agent 负责有限图和模型上下文，金额与数量仍由服务端确定性校验。
