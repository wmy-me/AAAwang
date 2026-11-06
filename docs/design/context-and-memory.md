# 对话上下文与长期记忆方案

- 状态：设计提案；030 已完成会话短期上下文与统一执行预算，长期记忆仍未实现。
- 029 与 030 均已完成；后续各项按独立编号任务拆分，本文不授权全部实现。
- 参考 [GoGo MasterAgent](https://github.com/wmy-me/gogo-agent/blob/d7823df02887b01e31ffa094d06ab22653876098/src/main/java/com/gogo/travel/agent/MasterAgent.java)、[AgentMemoryFactory](https://github.com/wmy-me/gogo-agent/blob/d7823df02887b01e31ffa094d06ab22653876098/src/main/java/com/gogo/travel/agent/memory/AgentMemoryFactory.java)、[长期偏好工厂](https://github.com/wmy-me/gogo-agent/blob/d7823df02887b01e31ffa094d06ab22653876098/src/main/java/com/gogo/travel/agent/memory/TravelPreferenceLongTermMemoryFactory.java)、[LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)。

## 当前事实

会话消息、任务 revision、Run/事件和结果持久化于 PostgreSQL；存在任务条件与当轮工具循环上下文，不等于完整历史管理。030 已加入 owner-scoped `ContextBuilder`：它以当前输入的稳定游标在数据库中限制历史、按完整轮次裁剪，路由、Worker 直答和能力决策读取各自所需的同一会话有限文本视图，默认最多 12 条消息和 12,000 字符，assistant 仅在关联 Run 已完成时进入视图。路由模型已迁入 durable Worker Run；模型、委派、发现和 MCP 的每次预占都持久化到带 fencing 的 `RunBudget` 快照。030 已按修订范围完成，浏览器交互仍未验证，详见 030 报告。当前未见跨会话长期偏好存储/召回或图 checkpoint 恢复的生产实现。数据存储不等于所有历史都会送入模型。

## 四层职责

| 层 | 内容和范围 | 数据与生命周期 |
| --- | --- | --- |
| 当前执行上下文 | 系统提示、授权能力、当前消息、相关任务 revision、有限工具证据 | Run 临时视图，权限及预算由代码约束 |
| 会话短期上下文 | 当前会话近期消息、必要的历史摘要、当前任务/待澄清状态 | PostgreSQL 原始消息为事实，摘要为可重建派生数据 |
| 跨会话用户记忆 | 用户长期明确偏好及已确认事实，如价格档位、饮食禁忌 | 受 owner 隔离、可查看纠正删除；不自动把本次预算写成长期偏好 |
| 知识库 RAG | 投稿/文档的分片、检索、引用和发布状态 | 与个人记忆隔离，按 owner/发布权限过滤 |

LangGraph checkpointer 保存线程图状态以恢复执行；不等于消息数据库、用户长期记忆或业务记录。若未来引入 PostgreSQL checkpointer，定义 thread_id 与 owner/conversation/run 的绑定、授权、清理、checkpoint 版本与 Worker 租约/fencing 的协调；外部调用仍可能重复，不保证 exactly-once。

## 请求组装方案

后端唯一 ContextBuilder 在认证与 owner 校验后按序组装：稳定角色/安全规则、已授权工具与预算、当前消息及相关 task/revision、近期完整对话轮次、必要会话摘要、按需召回的少量长期记忆、当前工具证据。各层设置可配置 token 预算并在超限时按优先级裁剪；不得截断 tool_call/tool_result 配对或破坏消息协议；不要为每轮机械注入全量历史/记忆。若无任务则只构建对话上下文。专业 Agent 只收到职责相关的最小上下文。

初期采用近期消息窗口；超限后可选择后台摘要，记录覆盖的消息范围、版本和更新时间，保留原文，避免摘要覆盖后续消息；摘要失败时回退较小窗口。摘要不能作为修改权限或确定性金额计算依据。监控上下文 token、裁剪/摘要次数、延迟，不记录密钥、思维链或完整敏感内容。

## 长期偏好首版

031 已完成 Mem0 OSS 适配代码，优先复用 PostgreSQL/pgvector 和可配置 Embedding；显式配置使用独立 PGVector collection、持久 history 路径和可配置模型/维度，真实可用性仍待运行时验收，详见 [031 报告](../reports/031-user-preference-memory-report.md)。DeepSeek Key 不等于 Embedding 配置。记忆仅保存用户明确要求记录的长期偏好，用户可通过对话查看、更正和删除；本轮要求高于历史偏好，临时条件不自动成为长期记忆。

后端从认证上下文注入用户 ID，限制召回范围、数量和内容长度；记忆作为不可信数据，不能变更 system、权限或工具白名单。Mem0 操作应适配现有 Worker 和共享预算，记忆不可用时普通对话降级，显式写入失败须告知用户。密码、密钥和支付凭据等不作为默认记忆；记忆与文档 RAG 分开管理。以上是待执行设计，并非已实现。

## GoGo 借鉴与差异

GoGo 的 MasterAgent 使用 AutoContextMemory + AutoContextHook 管理上下文压缩，并用按 userId 创建的百炼长期记忆（未配置时可退化）；其子 Agent 注册与工具白名单可供参考。AAAwang 是 Python/LangGraph + PostgreSQL：借鉴按场景控制上下文和用户隔离，不照搬 Java/百炼、数值阈值或声称已经拥有该能力。上下文 token 阈值、摘要模型和成本需通过样例评估。

## 分阶段与验收

1. **029 内**：完成纯对话入口、taskless Worker、消息持久化、多轮任务关联和最小近期消息窗口；同会话代词/追问、不同任务歧义、双账号与刷新重读。若 029 当前实现不含上下文组装，记录差距并在该任务验收，不要求同时实现长期记忆。
2. **后续上下文任务**：抽取唯一 ContextBuilder、消息/工具对裁剪、摘要触发和增量更新；真实模型+PostgreSQL+浏览器验收长对话、重启重读、摘要失败回退、预算计数与不会跨用户混入。
3. **031 长期记忆任务**：接入 Mem0 开源 SDK，完成显式记住/查看/修改/删除与按需召回；范围和精简验收以 031 执行文档为准。
4. **后续**：文档知识库检索、图检查点和长期执行中断续跑分别规划；记录服务配置和外部依赖。

每个编号任务列明配置依赖及与范围匹配的少量关键验证；已完成的测试与设计提案分开写。
