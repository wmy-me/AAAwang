# 036 LLM Wiki 私有知识库最小闭环报告

- 状态：代码已实现，真实联调待补
- 任务：[036](../vibe%20coding/036-llm-wiki.md)
- 日期：2026-11-06

## 已实现

- 保留 `wiki_documents` / `wiki_pages` 迁移 `20261106_0023`：原文、owner、来源文件名、状态和错误摘要保存在 PostgreSQL；Wiki 页面保存标题、正文、来源片段和状态。
- 上传接口 `POST /api/wiki/documents` 接收 `conversation_id` 和 `.md`/`.txt` 文件，限制 200 KB、UTF-8、非空文本；按 owner + 内容哈希去重，跨账号不可见。
- 上传后由服务端创建绑定当前会话的用户消息和 taskless `wiki_index` Run；Worker 领取后调用现有 DeepSeek 整理页面。Run 复用现有租约、取消、fencing、共享预算和终态事务，不另建执行链。
- DeepSeek 输出受限 JSON `title/content`；原文是最低可信数据，提示明确禁止执行资料内指令或访问链接。生成失败时原文保留，文档标记 `failed` 并写入错误摘要。
- `GET /api/wiki/documents`、`GET /api/wiki/pages`、`DELETE /api/wiki/documents/{id}` 均按 owner 隔离；页面列表返回来源文件名，供前端展示。
- Worker 直答路径按当前问题做简单标题/关键词匹配，最多读取 5 个当前用户的 Wiki 页面，把页面摘要和来源文件名作为低可信上下文；没有匹配时不强制检索。
- 网页在对话输入区增加“上传资料”入口，展示资料状态、Wiki 标题和来源文件名，支持删除；上传后的 Run 沿用现有状态/SSE 显示。

## 验证

本轮按用户要求只运行方便的静态检查，不执行真实模型、数据库、Worker、浏览器或全量测试：

- `uv run ruff check`（本次涉及的 wiki/worker/run 文件）：通过。
- `uv run python -m compileall -q`（本次涉及的 backend 文件）：通过。
- `npm run lint`：通过，保留 1 条既有 React Hook warning。
- `npm run build`：通过。

## 未完成（不能视为真实通过）

- 尚未执行迁移 `20261106_0023`；真实 PostgreSQL 表未创建。
- 尚未用真实 DeepSeek、独立 Worker 和真实上传文件完成“上传 → Wiki 页面 → 新会话检索 → 删除后不再检索”的闭环。
- 未验证真实第二账号隔离、Run 取消/失租/失败状态、上传重试和页面刷新。
- 关键词检索不是语义检索，效果有限；PDF/Word/OCR、公共分享和版本历史不在本任务。
- 原始文本保存在 PostgreSQL，未使用对象存储；部署备份需同时覆盖数据库和 `backend/data/`（Mem0 历史，若启用）。
