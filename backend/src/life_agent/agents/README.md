# agents/

智能体层目录。本轮只预留职责与子目录，不包含 LangGraph 状态图、节点、提示词或 Agent 类。

| 子目录 | 后续职责 |
| --- | --- |
| `coordinator/` | 主协调 Agent：理解需求、拆分任务、调度专业子图并汇总结果 |
| `discovery/` | 信息发现 Agent：通过 MCP、搜索与知识检索收集候选信息 |
| `procurement/` | 采买规划 Agent：比较候选、计算预算并生成采买方案 |
| `travel/` | 出行规划子图：交通、酒店与每日行程安排 |

LangGraph 已在 `pyproject.toml` 中安装，但尚未创建任何图或检查点。业务开发需等待后续任务。
