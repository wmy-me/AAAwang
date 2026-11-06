# 031 基于 Mem0 的用户长期偏好记忆报告

- 状态：受阻，未验收完成
- 日期：2026-11-06
- 任务：[031](../vibe%20coding/031-user-preference-memory.md)

## 已核对的环境

- 已拉取并核对远端最新 `origin/main`：`10cb67a docs: align memory design with Mem0 plan`；任务已明确要求 Mem0 OSS，不能以自建偏好表替代。
- 现有项目实例为 `life-buy-agent-postgres`（`pgvector/pgvector:pg17`），在不清库、不删卷、不启动备用 Compose 的前提下，已对 `life_buy_agent` 执行 `CREATE EXTENSION IF NOT EXISTS vector`，得到 `vector:0.8.5`；数据库角色具备创建扩展权限。
- 当前仓库原本没有 `mem0ai`、`sentence-transformers` 或本地 Embedding 模型。已将 `mem0ai==2.2.1` 和 `sentence-transformers>=5.2.0,<6` 写入 `backend/pyproject.toml` 与 `uv.lock`，但安装过程需下载大型 PyTorch/CUDA 依赖，尚未完成可导入验证，更未下载/验证任何中文 Embedding 模型。

## 不能作为完成证据的内容

- 没有完成 Mem0 `Memory.from_config` 到 PostgreSQL/pgvector 的初始化、没有确认 Mem0 的历史 SQLite 持久化路径，也没有用真实 DeepSeek、Embedding、Mem0、PostgreSQL 做“记住→新会话召回→删除→重启读取”闭环。
- 浏览器、完整回归和故障矩阵均未运行，且不属于本任务的必要重跑范围。
- 工作区保留了中断前未提交的实验性自建偏好模块；它不是 Mem0 实现，不能提交、不能视为 031 交付，也不会在本报告中当作完成结果。

## 唯一阻塞与继续方式

需要先完成并验证本地 Embedding 运行时，再实现和验收 Mem0 适配层。建议在 `backend/.env`（不提交）配置：

```dotenv
MEM0_EMBEDDER_PROVIDER=huggingface
MEM0_EMBEDDER_MODEL=BAAI/bge-m3
MEM0_EMBEDDING_DIMENSIONS=1024
MEM0_COLLECTION=life_agent_preferences
MEM0_HISTORY_DB_PATH=backend/data/mem0_history.db
```

还需让依赖安装完成（建议 CPU 版 PyTorch，避免下载 CUDA 运行时），并允许首次从 Hugging Face 下载 `BAAI/bge-m3` 的本地模型文件。DeepSeek 的既有 LLM 配置只能供 Mem0 的提取步骤使用，不能代替 Embedding 配置。完成后将以同一 PostgreSQL 的独立 `life_agent_preferences` collection、显式持久 history 路径和现有 Worker/RunBudget 接入，保留用户 ID 服务端注入、按需少量召回及删除后不返回的约束。
