# agents/

智能体层目录。022 已将受限 coordinator、discovery、procurement 入口接入生产路径；旧购物图仍保留兼容入口，travel 仍为预留。

| 子目录 | 后续职责 |
| --- | --- |
| `coordinator/` | 受限主协调：结构化决策、能力可见集和执行前 MCP 发现校验 |
| `discovery/` | 商品发现入口和提示词；天气/地点等只读能力由 Worker 适配器执行 |
| `procurement/` | 确定性候选校验、预算计算和采买方案边界 |
| `travel/` | 出行规划子图：交通、酒店与每日行程安排 |

`shopping_agent` LangGraph 图已保留为有限主从购物入口；它没有图检查点或长期记忆，不代表完整通用 Agent。天气能力不是 LangGraph 图，而是 coordinator 选择后的受控 Worker/MCP 路径。
