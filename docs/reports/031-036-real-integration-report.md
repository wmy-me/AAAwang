# 031/036 真实联调记录

- 日期：2026-11-06
- 代码基线：`6f56fb7552d8a206695a9ae465c56049194acc73`
- 代码修复提交：`28321fa3054d8c5c569fd3e37efd4ec5cf7ed116`
- 独立分支：`qa/031-036-real-173546`
- 独立 worktree：`/tmp/aaa-031-036-real-20261106-173546`
- 说明：037 尚未提交；本记录只代表上述基线加本分支修复，不代表 037 修改后的 Wiki/Worker 行为。

## 隔离环境

- 测试数据库：`life_buy_agent_qa_031_036_H3619`，位于已有 pgvector PostgreSQL 实例中的独立数据库；未对业务库 `life_buy_agent` 执行迁移、清库或删除。
- 测试 API/Worker 使用独立端口 `18000`（036）和 `18001`（031），未停止或复用当前项目 `8000` 端口的进程。
- 测试账号和资料均为本次新建的 QA 账号；未使用真实用户数据。
- 031 测试集合：`life_agent_preferences_qa_031`，`vector(512)`。
- 031 测试 Embedding：本地 `BAAI/bge-small-zh-v1.5`（512 维，CPU）。项目默认仍是 `BAAI/bge-m3`（1024 维）；两者不是同一个模型，不能把本次结果写成 bge-m3 已验证。
- 031 测试 Mem0 history：`/tmp/aaa-031-mem0-history-*.db`；生产默认仍是 `backend/data/mem0_history.db`。
- 031 测试环境设置 `MEM0_TELEMETRY=false`；该变量需要进入进程环境，不能只写在 `.env` 中指望应用自动导出。
- 036 测试环境未启用 Mem0。

## 036 真实结果

入口：`POST /api/wiki/documents`、独立 Worker、`GET /api/wiki/pages`、新会话 `/conversations/{id}/turns`、`DELETE /api/wiki/documents/{id}`。

通过项：

1. `alembic upgrade head` 在隔离库执行成功，包含 `20261106_0023`。
2. 上传 `travel.md`（UTF-8 Markdown，含唯一随机核对暗号）返回 200，`wiki_index` Run 完成。
3. 真实 DeepSeek 生成 Wiki 页面：标题《毕业旅行计划》，页面状态 `ready`，来源文件名为 `travel.md`。
4. 新建会话提问后，回答包含唯一暗号和出发日期，并写出“来源：毕业旅行计划”；`/api/wiki/pages` 同时返回 `source_filename=travel.md`。
5. 第二账号 `/api/wiki/pages` 为空；删除第一账号资料返回 404。
6. 第一账号删除资料返回 204；删除后 `/wiki/pages` 和 `/wiki/documents` 均为空。
7. 删除后新会话再问，回答不再包含唯一暗号、页面标题或来源文件名。
8. 上传文本未改变工具权限；本次只验证读取资料后的直答路径。

限制/未完成：

- 回答内联来源是 Wiki 页面标题，不是来源文件名。当前 `_run_direct_answer_with_lease` 的上下文没有把文件名传给模型；文件名可在 `/api/wiki/pages` 和网页列表中核对。若要求回答必须写 `travel.md`，需要在 037 完成后再改 Worker 检索上下文。
- 未做浏览器矩阵、PDF/Word、上传失败重试、取消/失租故障路径。
- 本次 036 结果基于 037 之前的代码；037 对 Wiki 检索加入 `requested_wiki` 门槛，合并后需重新验证一次。

## 031 真实结果

入口：现有 `/conversations/{id}/turns` + Worker + `Mem0PreferenceService`，使用真实 DeepSeek、真实本地 Embedding、真实 PostgreSQL/pgvector。

通过项：

1. Mem0 成功初始化：pgvector collection 存在，向量列类型为 `vector(512)`，history SQLite 持久化。
2. 对话“记住我不吃辣。”被路由为 `memory/remember`，Mem0 写入 1 条记录，metadata 为 `饮食偏好/不吃辣`。
3. 新会话“查看我保存的饮食偏好。”召回该记录，回答包含“不吃辣 / spicy”。
4. 新会话“推荐餐厅时要注意什么？”作为普通聊天回答，并引用长期偏好“不吃辣”。
5. 第二账号查询返回“（暂无）”，Mem0 行数为 0；第一账号行数仍为 1。
6. 重启 API 和 Worker 后，新会话仍能列出并引用该偏好，Mem0 行数为 1。
7. 对话“忘记我不吃辣。”删除成功，返回“已忘记”，Mem0 行数为 0。
8. 删除后新会话列表为“（暂无）”；再次重启后仍为“（暂无）”，Mem0 行数为 0。
9. 删除后的普通聊天回答是通用建议，没有把“不吃辣”作为该用户的记忆内容返回；判断以 Mem0 行数和列表结果为准。

限制/未完成：

- 项目默认 `BAAI/bge-m3`（1024 维）未完成下载验证。下载在约 67 MB 后长时间停滞，本次改用 `bge-small-zh-v1.5`（512 维）完成真实链路；生产前需下载 bge-m3 或配置兼容 Embedding 服务，并使用新 collection。
- Mem0 默认事实抽取会把中文偏好整理成英文（例如 `User does not eat spicy food...`），列表回复会出现中英混合；聊天回答会翻译成中文。这是质量问题，不影响本次写入/召回/删除链路。
- 意图路由存在非确定性：同一句“我的饮食偏好是什么？”曾返回 ambiguous；改用“查看我保存的饮食偏好。”可稳定路由为 list。报告不能声称所有自然语言同义表达都已覆盖。
- “忘记我不吃辣。”可能被路由成不同的 category/key（例如 `food_preference/不吃辣`），与写入时的 `饮食偏好/不吃辣` 不一致。本次已加入 owner 范围内语义匹配回退，并用直接服务测试验证不同标签也能删除；回退阈值为 0.45，避免只存在一条无关记忆时误删。
- Mem0 的 spaCy 实体抽取因未安装 `mem0ai[nlp]` 被跳过，核心记忆链路不受影响；若需要实体链接需补装。
- 未跑全量 pytest、浏览器或取消/失租故障矩阵；只运行了本次相关的 3 个记忆单元测试、Ruff、compileall 和真实联调。
- 未验证远程 Embedding、Mem0 云服务、第二账号修改/删除第一账号记忆的 API 级攻击路径（本次只验证第二账号读不到、行数隔离）。

## 本次修复

| 文件 | 问题 | 修复 |
| --- | --- | --- |
| `backend/pyproject.toml`、`backend/uv.lock` | Mem0 pgvector 导入需要 `psycopg_pool`，原依赖只有 `psycopg[binary]` | 改为 `psycopg[binary,pool]`，锁定 `psycopg-pool` |
| `backend/src/life_agent/modules/wiki/service.py` | 中文自然语言查询被整句当作关键词，`出发日期是哪天` 无法匹配页面中的 `出发日期`，036 新会话检索失败 | 增加有界 2/3/4 字 n-gram 与停用词过滤，按命中数排序 |
| `backend/src/life_agent/modules/memory/service.py` | 意图路由返回中文 category（如 `饮食偏好`），`_safe` 只接受 ASCII，导致“记住”被误判为敏感/非法；忘记时 category/key 与写入不一致会找不到 | 允许 CJK category；forget/update 精确匹配失败时在 owner 范围内按原消息语义检索，要求相似度 ≥0.45 且唯一命中，否则澄清 |
| `backend/src/life_agent/worker/runner.py` | 语义回退需要原始用户消息 | `_run_memory_action_with_lease` 传入 `request_text` |

## 037 可能冲突文件

- `backend/src/life_agent/modules/wiki/service.py`：本分支改 `search`；037 改 `index_document` 提交围栏。同文件、不同函数。
- `backend/src/life_agent/worker/runner.py`：本分支改 `_run_memory_action_with_lease`；037 改 `_run_wiki_index_with_lease` 和 `_run_direct_answer_with_lease`。同文件、不同 hunk。
- `backend/pyproject.toml`、`backend/uv.lock`：037 目前未见修改，但合并时需重新 lock。
- 本报告为新文件，预计不与 037 报告冲突。

## 用户需要补的配置

1. 本地 Embedding：下载 `BAAI/bge-m3`（约 2.27 GB）或提供兼容的远程 Embedding；设置 `MEM0_EMBEDDER_MODEL`、`MEM0_EMBEDDING_DIMENSIONS=1024`，使用新的 collection（不要混用 512/1024 维）。
2. 启用记忆：在进程环境设置 `MEM0_ENABLED=true`，并确保 Worker 与 API 使用同一数据库和 Embedding 配置。
3. 安装锁定依赖：部署/本地环境执行一次 `uv sync --locked`，使 `psycopg-pool` 生效。
4. 如需关闭 Mem0 PostHog 遥测：在进程环境设置 `MEM0_TELEMETRY=false`；仅写 `.env` 不一定会被 Mem0 SDK 读取。
5. pgvector 扩展权限：Mem0 首次连接会执行 `CREATE EXTENSION IF NOT EXISTS vector`，数据库角色需要相应权限；本次 QA 角色为超级用户。
6. 备份：PostgreSQL 卷和 `backend/data/mem0_history.db`（或配置的持久 history 路径）需要一起备份。

## 复现与清理

- 测试脚本：`/tmp/run_036_acceptance.py`、`/tmp/run_031_acceptance.py`。
- 测试结果：`/tmp/aaa-036-result.json`、`/tmp/aaa-031-result.json`。
- 测试数据库和账号保留在隔离库 `life_buy_agent_qa_031_036_H3619` 中，便于复核；未清理业务库。
- 测试进程已停止；未停止当前项目正在运行的 API/Worker。
