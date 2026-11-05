# coordinator/

当前职责：为持久化 Run 提供受限的结构化能力决策入口。它接收服务端已校验的任务目标、
revision、消息和共享 `RunBudget`，只返回 direct、clarification 或后端可见能力集合中的
capabilities。

Worker 仍负责领取、租约、取消、fencing 和终态事务；本目录不拥有身份授权、MCP URL、
预算实例或数据库写入。当前是一次有界模型决策，不是开放式多轮 ReAct 或完整出行协调图。
