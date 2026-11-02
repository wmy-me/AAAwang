# 当前进度

核对日期：2026-11-02。006 从 `main` 提交 `9c394b0258f7c177de02378ae88cb577a8e81380` 开始执行；以下根据源码、本轮真实 PostgreSQL 17 和自动测试结果记录。

## 代码现状

| 能力 | 事实与证据 |
| --- | --- |
| 工程骨架 | `backend/`、`web/`、`mcp-services/` 及锁文件已存在 |
| Python | 提供健康、认证、私有对话、用户消息、私有任务与条件版本 API；已有服务端会话、DeepSeek、通用 MCP 和有限工具循环；LangGraph 仍仅安装依赖 |
| 网页 | 初始化说明和真实健康检查按钮，没有业务界面 |
| Java | shopping-mcp 提供 Streamable HTTP `/mcp` 和一个只读模拟查询工具；另外两个服务保持健康检查骨架 |
| 基础设施 | PostgreSQL 17 Compose；Python 认证模块通过 SQLAlchemy/psycopg 连接，Alembic 管理迁移 |
| Agent 与工具 | 已验证 LLM 根据发现 schema 调用一个允许的只读 MCP 工具并依据结果回答；仍无 LangGraph 图或 Agent |
| 业务能力 | 已有账号、登录会话、私有对话、手工用户消息、私有任务和条件版本；尚无 run、方案、投稿、知识库、实际出行规划或交易实现 |
| Android | 只有说明文件 |

## 完成证据与限制

[000 初始化报告](reports/000-initialization-report.md)记录了当时的依赖安装、构建与进程健康检查。浏览器按钮交互未验证；数据库当时采用临时 5433 端口验证，默认 5432 被其他容器占用。这是执行者的历史报告，不应写成后续每次审查都重新通过。

截至本次复核，GitHub Actions 无运行记录。前次源码审查另发现健康响应的 `service` 字段校验不完整，以及报告中 Vite `/docs` 代理验证描述不准确；本次按讨论范围未处理这些小项。

## 001 已提交结果（执行报告证据）

- 已按 DeepSeek 官方 OpenAI 格式接入 `deepseek-flash`，Base URL 为 `https://api.deepseek.com`，使用异步 OpenAI Python SDK。
- 模型配置保持可选；无密钥时 FastAPI 可导入，只有执行检查脚本时报告缺少 `LLM_API_KEY`。
- SDK 自动重试关闭，显式设置超时；本地测试覆盖成功、空响应、认证失败、模型不存在、超时和客户端初始化失败映射。
- 真实 DeepSeek 请求已成功：`deepseek-flash` 在 0.93 秒内返回非空文本，服务报告输入 15、输出 5、合计 20 tokens。该结果只证明普通文本调用连通。

## 002 已提交结果（执行报告证据）

- Python 使用官方 MCP SDK 2.3.0，通过同一客户端按服务 ID连接；工具身份包含服务 ID，保留 SDK schema、内容块、结构化结果和错误标志。
- shopping-mcp 使用 Spring AI 2.0.2、MCP Java SDK 2.1.0 和 Streamable HTTP，仅注册只读 `search_products`；固定数据明确标记为模拟来源。
- 真实联调协商 MCP `2025-11-25`，发现 `shopping:search_products`，合法查询返回 2 个模拟候选；空结果与非法参数已通过真实协议分别验证为成功空集合和工具错误。
- shopping-mcp 只绑定回环地址；无效 Origin 最终返回 403。travel-mcp 和 local-life-mcp 未增加 MCP 或业务实现。
- Python 13 个测试、Ruff、编译与 uv 锁检查通过；Java 多模块 `verify` 通过，其中 shopping-mcp 6 个测试通过。

## 003 已提交结果（执行报告证据）

- 新增有限工具循环：只暴露允许列表中的发现工具，模型工具名稳定包含服务身份且满足供应商命名约束；模型不能提交服务 ID或 URL。
- 模型参数先解析 JSON并按 MCP 公布的 schema 验证；未知/未授权、多调用、重复调用和超限结果均不继续执行额外工具。
- 真实 DeepSeek `deepseek-flash` 发出结构化 tool_call，MCP `2025-11-25` 调用 `shopping:search_products` 一次，第二次模型请求基于返回结果回答。
- 真实回答引用“彩色铅笔套装”模拟价格 12.8 CNY，并明确声明商品与价格为模拟信息；检查脚本机器核对来源、候选名和价格。
- 工具循环 9 项聚焦测试覆盖正常调用、直接回答、非法参数、授权边界、次数上限、空结果及跨服务映射；001 与 002 的 13 项测试继续通过。

## 004 已提交结果（执行报告证据）

- 新增 SQLAlchemy 2.1.6、psycopg 3.3.6、Alembic 1.20.1 和 Argon2 依赖；数据库 URL 使用秘密类型配置。
- Alembic `20261102_0001` 创建用户与登录会话；真实 PostgreSQL 17 空库上重复升级、降级重建及 `alembic check` 均通过。
- 注册、登录、退出和 `/me` 使用请求级受信身份依赖；会话秘密随机生成，数据库仅保存 SHA-256 摘要，密码保存 Argon2id 哈希。
- 本地 Cookie 为 HttpOnly、SameSite=Lax、Path=/；生产配置强制 Secure。注册、登录、退出均拒绝恶意 Origin/cross-site Fetch Metadata。
- 两个账户身份不混用；额外 `user_id` 被请求 schema 拒绝。登出、到期和数据库停服分别验证为 401/401/503，健康接口在数据库停服时仍为 200。
- 真实 Vite `/api` 代理完成注册、登录、`/me`、跨站 403 与登出；Python 全量 27 项测试及静态检查通过。

## 005 已提交结果（执行报告证据）

- Alembic `20261102_0002` 创建 `conversations` 与 `messages`，owner 外键级联删除；复合索引提供确定排序，数据库唯一约束兜底客户端消息幂等。
- 六个 REST 接口支持建立、列表、读取、改标题、追加用户文本和读取消息；owner 只取自 `CurrentUser`，额外 owner/user/role 字段被拒绝。
- 别人的对话与不存在的对话统一 404；相同客户端 ID 同正文重试返回原消息，不同正文返回 409；写请求沿用受信 Origin 检查。
- 真实 PostgreSQL 17 空库升级、重复升级、005 单独降级/重升及 `alembic check` 均通过。A、B 双向读写隔离、新客户端持久化读取及数据库消息行数已核对。
- Python 全量 31 项测试、Ruff、compileall 与锁文件检查通过。停库时健康接口 200，带有效 Cookie 的对话请求安全返回 503。

## 006 已执行结果（本轮证据）

- Alembic `20261102_0003` 创建 `tasks` 与 `task_revisions`；每个任务指向当前版本，每个 revision 保存完整不可变 JSON 条件快照。
- shopping/travel 使用受控字段和类型；任务创建与 revision 1、新快照与当前版本更新分别原子提交。相同快照明确提交也创建新版本。
- owner 经私有对话验证；跨账号创建、列表、读取和修订统一 404。过期 `expected_revision` 返回 409 及当前版本。
- 真实 PostgreSQL 17 从 005 head 升级、重复升级、006 单独降级/重升及 `alembic check` 均通过；两个并发请求基于同一版本实际得到 201/409。
- Python 全量 35 项测试、Ruff、compileall 与锁文件检查通过。停库时健康接口 200，带有效 Cookie 的任务请求安全返回 503。

## 每次读取最新 GitHub 时的检查方式

1. 明确默认分支或用户指定分支，读取最新提交 SHA，并与本页基线比较。
2. 读取 `CLAUDE.md`、文档导航、本页、相关执行任务和报告，再检查变更代码与可用 CI 结果。
3. 将计划、已实现、已验证、未验证和阻塞分别说明。源码和可复核结果优先于旧进度声明；新用户决定优先于历史任务范围。
4. 依据当前目标与依赖推荐一个可验收的小任务，说明它解决什么、为何现在做及完成标准。
5. 讨论确定后生成 AI 执行文档；实施者完成后更新报告与本页，写明审查过的代码提交。
6. 若代码已前进而进度页未更新，先指出差异，不能机械重复上一轮计划。

用户每次主动请求查看仓库时执行上述流程；没有自动轮询或后台监控。

## 当前状态与下一步

截至 2026-11-02 已核对最新代码提交 `56be3b6c044fa57a431f1fb3c8aa1f4697aa5cb4`：006 的模型、迁移、五个任务接口及报告已提交。报告记录 35 项 Python 测试通过、真实 PostgreSQL 双用户隔离与并发提交 201/409；本次只审阅仓库及报告，未在当前环境重跑数据库或测试。已新建待执行 [007 持久化 Run 与最小 Worker](vibe%20coding/007-persistent-runs-worker.md)，先建立独立执行记录、版本绑定、幂等与多 Worker 领取/恢复；SSE 和 Agent 执行仍拆为后续任务。

[001](vibe%20coding/001-llm-connection.md)至[006 私有任务与条件版本](vibe%20coding/006-task-revisions.md)均已完成；006 证据见[报告](reports/006-task-revisions-report.md)。P2 已有认证、私有对话、任务条件快照和并发修改保护；run、Worker、SSE、网页对话和 Agent 接入仍待后续任务验证。

## 2026-11-02 架构讨论归档

在仓库 `8459e40` 基础上记录 Agent 分类、协作、Tools 与 MCP、RAG、意图识别讨论，入口见 [设计索引](design/README.md)。此段是当时设计归档；目前 P1 的 001–003 与 P2 的 004–006 已完成，私有对话、任务和条件版本隔离已验证；完整 Agent、自动意图路由和 RAG 尚未实现。

PostgreSQL + pgvector 为推荐检索基线；分块和召回数为实验起点，Embedding 和重排型号及分类阈值仍需评估。当时的讨论只更新设计与导航；之后 002–006 均已完成。仓库自带 PostgreSQL 17 Compose 未配置 pgvector；用户其他实例的扩展状态尚未核对。
