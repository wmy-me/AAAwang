# 031 基于 Mem0 的用户长期偏好记忆报告

- 状态：代码完成，真实 Mem0/pgvector 主流程待验收
- 日期：2026-11-06
- 任务：[031](../vibe%20coding/031-user-preference-memory.md)

## 本轮实现

- 新增 `Mem0PreferenceService`，是唯一的长期偏好读写适配层。它使用 Mem0 OSS 2.2.1 的实际 `Memory.from_config`、`add`、`search`、`get_all`、`update`、`delete` 接口；业务层不再读写自建 `UserPreference`。
- Mem0 配置显式指定 DeepSeek LLM、HuggingFace 本地 Embedding、`BAAI/bge-m3`、1024 维、`life_agent_preferences` PGVector collection 和持久 `backend/data/mem0_history.db`。没有使用 Mem0 默认 OpenAI、临时 Qdrant 或临时 history 路径。模型文件及 history 文件均不提交；`backend/data/` 已忽略。
- Worker 沿用现有 durable Run、租约与 fencing。路由模型先识别受控的 memory 操作；写入时在 Mem0 可能发起事实提取前对同一 `RunBudget` 预占一次 `model`，预占会经既有 fencing 持久化。同步 Mem0 调用期间也会续租，调用前后复核取消；失租后不提交 Run 结果。检索只将最多 4 条、每条最多 500 字符的 owner-scoped 结果作为低可信上下文；不可修改 system、权限、工具白名单或预算。
- owner 只来自 `RunClaim`，不接受模型或前端指定 user ID。Mem0 的 `user_id` 和检索 filter 均由服务端注入。写入 metadata 保留 category、key、源消息 ID 和 explicit scope；同一源消息的重领会先查 metadata，避免重复添加。外部 Mem0 调用仍不能声称 exactly-once：调用后进程中断时以源消息查询恢复为最佳努力。
- 用户只在模型明确路由 `remember/list/update/forget` 时操作长期偏好；普通聊天、临时预算和一次性数量不会自动写入。敏感的密码、密钥、验证码、证件、银行卡和支付资料在适配器入口拒绝。
- 写入、删除、列表失败会返回明确的“没有完成”反馈；召回/初始化失败被隔离，普通 direct answer 继续。`user_preferences` 是此前自建实验表，不再是事实来源；新迁移将它重命名为 `legacy_user_preferences_pre_mem0`，不删除已有行，避免新部署继续创建第二套活跃偏好表。

## 配置、持久化与迁移

`.env.example` 增加以下非敏感配置，默认关闭，避免未下载模型时影响普通聊天：

```dotenv
MEM0_ENABLED=false
MEM0_COLLECTION=life_agent_preferences
MEM0_EMBEDDER_MODEL=BAAI/bge-m3
MEM0_EMBEDDING_DIMENSIONS=1024
MEM0_HISTORY_DB_PATH=backend/data/mem0_history.db
MEM0_RECALL_LIMIT=4
```

启用前在受保护的根目录 `.env` 或进程环境将 `MEM0_ENABLED=true`；既有 `LLM_*` 配置提供 DeepSeek，不要复制或提交 key。目标 PostgreSQL 已在此前检查中确认 `pgvector 0.8.5`，Mem0 首次连接会创建独立 collection 和索引；数据库角色须拥有该 collection 的建表/索引权限。更换模型或维度必须改用新 collection（或经明确迁移重建向量），不得把不同维度混入原表。Mem0 history SQLite 位于上述持久路径，应与 PostgreSQL 卷一起纳入部署备份；删除会删除正常召回的向量记录，但历史审计和已有备份的保留/清理取决于 Mem0 history 与部署备份策略，未承诺物理擦除所有副本。

`20261106_0022` 是数据保留迁移，尚未在本轮数据库执行；它只重命名原实验表，绝不清库、删卷或删除偏好数据。

## 已实际运行的验证（替身）

项目当前 `.venv` 可导入 Mem0，但没有 `pytest` 或 Ruff 开发依赖，且本轮按用户决定未运行 `uv sync`。因此以项目 Python 3.12 执行了 `tests/test_user_preference_memory.py` 的三个测试函数，使用受控 FakeMem0 替换 DeepSeek、Embedding 和 PGVector I/O：结果 `memory-fake-tests-ok`；另运行 `compileall` 和 `git diff --check`，均成功。

- 记住 → 同账号按需召回 → 更新 → 删除 → 不再召回通过；同一持久消息重试没有第二次 `add`。
- 第二 owner 查询为空；敏感内容拒绝；非 memory action 的临时预算没有写入；模型预算为零时在 Mem0 `add` 前停止；模拟 Embedding 查询故障会转为 `MemoryUnavailableError`，供 Worker 降级。

这只是接口和控制边界验证，不是 Mem0 SDK、Embedding、DeepSeek 或 PostgreSQL 的真实证据。

## 尚未运行，不能标记通过

- 按用户本轮指示，未再运行 `uv sync`、未下载/加载 `BAAI/bge-m3`，未生成真实 1024 维向量；当前本地 torch 环境保持不变。
- 未以 `MEM0_ENABLED=true` 构造真实 Mem0 client，未创建/检查 PGVector collection，未执行迁移，也未调用 DeepSeek。故“记住 → 新会话召回 → 删除 → 重启持久化”的真实闭环、真实账户隔离与真实失败反馈均未验收。
- 未跑完整 pytest、Ruff、浏览器或全量回归；这不属于本轮允许的验证范围。

恢复真实验收时，只需准备完成的本地 Embedding 运行时和现有数据库/DeepSeek 配置，启用 `MEM0_ENABLED=true`，先执行迁移，再按 031 的一条真实 API 对话流程验证。不得将本报告的替身结果当作真实模型或持久化通过。

## 用户当前决定与后续事项

用户目前只有 DeepSeek 模型 API，没有其他已配置模型或 Embedding 服务。Mem0 本阶段先保留接入代码，真实 Embedding、Mem0/pgvector 联调与迁移暂缓，不阻塞 032；用户下次询问缺少的服务或配置时再说明。禁用状态下普通对话继续；不能称为已验证可用。已知代码问题：forget 当前经 _safe 要求 memory_value 非空，需在 032 修复并以替身检查，不能声称已修复。
