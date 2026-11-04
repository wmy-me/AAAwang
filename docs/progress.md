## 018 真实地图 MCP 地点查询

- 部分完成：已接入高德官方 Streamable HTTP MCP，配置拆分为 `MAP_MCP_URL`、`MAP_MCP_KEY`、`MAP_MCP_TIMEOUT_SECONDS`、`MAP_MCP_ENABLED` 和 `MAP_MCP_TOOL_NAME`；真实 Key 仅保留在本地 `.env`。
- 真实握手协商 `2025-03-26`，发现 `amap-sse-server 1.0.0` 和 `maps_text_search`；上海“礼品店”查询返回 20 个 POI，结果标记 `simulated=false`。
- 适配高德文本 JSON 返回，新增认证私有地点查询 API；地点结果首版不持久化、不进入商品候选和金额复算。
- 后端全量测试 `73 passed`，Ruff、compileall 通过；本地数据库已升级到 `20261104_0014`，`alembic check` 通过；前端 lint/build 通过（2 条既有警告）。
- 已补入：`map_places` Run、任务聊天地点分支、城市/关键词解析测试、缺位置澄清、地点表迁移、owner/revision/Run 绑定、幂等/取消/fencing 复用、私有刷新 API 和网页城市/关键词入口。
- 未完成：真实 PostgreSQL 地点 Run 写入/刷新与浏览器闭环、DeepSeek→地图任务回合复验、主协调完整 Graph 条件路由、按任务上下文生成工具注册，以及认证/协议/限流/超时 HTTP 错误细分。路线、天气、真实商品价格/库存和下单仍未实现。

## 016 已选购物任务方案调整

- 新增 `20261103_0012` 不可变手动调整及方案项表；按 owner、task、revision、Run
	快照绑定，旧 015 `shopping_plans` 不更新。
- 新增任务级调整 POST/GET API，服务端统一复算多商品金额、覆盖人数和预算；客户端不
	提交价格或总额。请求指纹、任务锁和版本前提覆盖幂等与并发竞争。
- 网页已加入候选选择、包装数量编辑、提交和历史版本展示；验收中修复了保存后历史同时
	显示两个“当前”的前端状态问题。
- 真实 DeepSeek、Java `shopping-mcp`、独立 Worker、PostgreSQL 和 Chromium 已完成隔离
	账号闭环：REV1 自动方案 ¥6.90，多商品 V1 ¥13.40，同键重试复用原版本，双请求并发得到
	201/409，跨账号读写均 404；REV2 预算改为 180 元后新 Run 生成独立方案，旧 Run 方案仍
	可读取，V3 绑定 REV2，历史上只有一个当前版本。
- 真实网页完成候选选择、文具套装 ×25 调整、保存、刷新重读和旧 REV1 切换；登录后无异常
	请求。Python 全量 `59 passed`，Ruff、compileall、Alembic check、前端 lint/build、
	Java `verify` 通过。
- **遗留项已收口：** 目标文本（总预算 200 元）与 REV2 结构化预算 180 元的矛盾在 016 验收
	时未被提示；017 后续实现目标冲突提示、确认修订与 Run 前门禁，并用真实 DeepSeek/MCP
	新 Run 完成闭环。016 §3.4 已补齐，016 可整体标记完成。

## 017 任务目标与结构化条件一致性

- 已实现目标与结构化条件的 revision/Run 快照、0013 回填迁移、服务端冲突检查，以及手动
	Run 和任务聊天 turn 的 409 前门禁；Worker 只读取 Run 快照。
- 已同步任务 REST 契约、前端任务字段和修订请求参数；加入 017 测试后 Python 全量
	`61 passed`，Ruff、compileall、Alembic check、前端 lint/build 通过。
- 真实浏览器已验证冲突展示、Run 禁用、确认生成新 revision 及刷新一致；补验在隔离账号
	新建“目标 200 / 条件 180”任务：手动 Run 与聊天 turn 均 409，且没有新增 Run 或消息；
	确认后生成 REV2，目标修正为 180 元。真实 Run `ce9145dc-fa5d-45a4-a86d-0b6c91a5fcb5`
	`completed`，`model_requests=4`、`mcp_call_count=1`，保存 2 个模拟候选，方案预算
	¥180.00、合计 ¥6.90、余量 ¥173.10、覆盖 25/25 人。017 已完成；外部调用仍不承诺
	exactly-once。
# 当前进度

核对日期：2026-11-03。以下按 001–017 的对应执行报告和最新源码归档；013 的规划基线为 `main` 提交 `ba69c6e7180c700333d9fd6ea15d1a614796f8b3`，014、015、016 在其后的工作区变更上完成并已在真实 PostgreSQL、真实 Worker/DeepSeek/MCP 和浏览器中重新验收，017 于提交 `3f61900` 后完成真实新 Run 补验。

## 代码现状

| 能力 | 事实与证据 |
| --- | --- |
| 工程骨架 | `backend/`、`web/`、`mcp-services/` 及锁文件已存在 |
| Python | 提供健康、认证、私有对话、用户消息、私有任务、条件版本、持久化 run 与已选任务对话回合 API；已有服务端会话、DeepSeek、通用 MCP、有限工具循环和独立 Worker；成功 Run 写入唯一 assistant 消息；LangGraph 已有最小 `shopping_agent` 主从委派图，无检查点或完整多 Agent |
| 网页 | 已有网页登录、私有购物任务、版本化条件、shopping_agent Run、SSE状态、结果工作台和任务对话面板；013 的登出刷新、独立 SSE 与 014 的两轮消息刷新重读已验收 |
| Java | shopping-mcp 提供 Streamable HTTP `/mcp` 和一个只读模拟查询工具；另外两个服务保持健康检查骨架 |
| 基础设施 | PostgreSQL 17 Compose；Python 认证模块通过 SQLAlchemy/psycopg 连接，Alembic 管理迁移 |
| Agent 与工具 | 已验证 LLM 根据发现 schema 调用一个允许的只读 MCP 工具并依据结果回答；已有最小 LangGraph `shopping_agent` 主从委派图；仍无完整多 Agent、自动意图路由或长期记忆 |
| 业务能力 | 已有账号、登录会话、私有对话、手工用户消息、私有任务、条件版本、版本绑定 run、持久化 Run 事件、私有 SSE、shopping_agent 决策结果和已选任务两轮对话/assistant 回复；尚无方案、投稿、知识库、实际出行规划或交易实现 |
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

## 007 已执行结果（本轮证据）

- Alembic `20261103_0004` 创建 `runs`；每个 run 保存 owner、task revision ID/版本号和完整条件快照，并有 task 内幂等键唯一约束。
- 新增创建、列表、读取和取消 REST；创建事务锁定 task 并核对 `expected_revision`，旧 run 不读取后来 current revision。越权与不存在统一 404，过期版本和幂等冲突返回 409。
- 独立 Worker 使用 PostgreSQL 行锁、`SKIP LOCKED`、租约、attempt 和 fencing token；诊断 runner 只记录 task/revision 与“尚未运行 Agent 规划”，不调用 LLM、MCP 或写消息。
- SQLite 聚焦测试 4 项，Python 全量测试 **39 passed**；Ruff、compileall 通过。
- 真实 PostgreSQL 17 从 006 head 升级、重复升级、`alembic current` 和 `alembic check` 通过；API + 两个独立 Worker 验证幂等、单次领取完成、排队取消、租约过期接管和旧 Worker 迟到写入拒绝。
- 007 当轮未验证真实外部服务、网页、LangGraph 或 Agent 规划；008 随后的验证见本页 008 小节。本轮 `completed` 仅代表无副作用诊断 runner 完成。

## 008 已提交结果与验收边界

- Alembic `20261103_0005` 创建 `run_events`，状态转换与事件同事务；提供私有增量补读和 SSE 游标重连。报告记录 Python 全量 **41 passed**、Ruff、编译、锁文件检查通过。
- [008 报告](reports/008-run-events-sse-report.md)已经记录真实 PostgreSQL 17 从空库升级至 0005、重复升级、`alembic check`、真实 API 的 queued/cancelled 事件与两个独立 Worker 的 007 基础回归。此前根 `CLAUDE.md` 的“008 真实 PostgreSQL 联调仍需补做”与报告矛盾，现以报告为准。
- 报告也明确：**真实双 Worker 的完整事件序列与无缺失检查尚未单独验收**；旧租约接管、fencing 的事件约束在自动测试中覆盖。用户 ORM 级联删除与 `runs.task_revision_id ON DELETE RESTRICT` 在临时数据清理中发生冲突，不能视为已解决。
- 以上未验证项已由 [009 Run 删除链修复与事件真实并发回归](vibe%20coding/009-run-deletion-events-regression.md) 完成修复与验收；后续再按新任务决定是否接入Agent/网页。

## 009 已完成结果与验收边界

- 新增 `20261103_0006`，将 `runs.task_revision_id` 改为 `ON DELETE CASCADE`；相关ORM关系使用 `passive_deletes=True`，不改写已发布迁移。
- 自动测试已覆盖ORM删除链和跨用户隔离；Python全量测试 **42 passed**。
- 真实 PostgreSQL 17 已验证0005存量升级到0006不丢失Run、事件和revision关联，重复升级与 `alembic check` 通过。
- 真实双Worker竞争、数据库模拟租约接管、旧fencing拒绝、无幽灵终态事件及SSE `after=1`断线补读均通过。
- ORM用户删除与数据库父表直接 `DELETE` 均已验证级联清理Run和事件，另一用户数据保留；详见[009报告](reports/009-run-deletion-events-regression-report.md)。

## 011 开发数据库配置收敛

- 010 的真实 DeepSeek→shopping-mcp→PostgreSQL 已通过隔离临时数据库验收，但测试卷随后清理；这不证明用户本机项目库已长期运行。
- 010 提交后 `infra/compose.yaml` 默认含 PostgreSQL、MySQL、Redis、MinIO；后面三项尚无业务使用。两个 env 示例及 Compose fallback 的 PostgreSQL 用户/密码存在不一致，默认宿主 5432 与用户已有服务可能冲突。
- 011 已将根目录 `.env.example` 作为本地配置模板，后端从根目录 `.env` 读取并保留显式环境变量覆盖；默认 Compose 仅启动项目 PostgreSQL，宿主默认端口为 55432、默认用户为 `life_buy`，MySQL/Redis/MinIO 使用 `optional` profile。普通 `down` 保留项目命名卷，未触碰用户已有容器或卷。
- 项目真实卷已完成非破坏性角色对齐、`alembic upgrade head` 到 `20261103_0007`、隔离测试写入和普通 `down`/`up` 持久化验证；测试记录已删除，卷保留，用户其他容器未修改。详见 [011报告](reports/011-dev-database-config-report.md)。

## 012 主 Agent 与信息发现委派

- 新增 `shopping_agent` Run 类型、LangGraph `supervisor -> discovery -> finalize` 图和 0008 决策元数据迁移；旧 `diagnostic`/`shopping_research` 语义保留。
- 真实项目 PostgreSQL、真实 API、真实 Worker 和真实 Java shopping-mcp 完成端到端：Run `completed`，`delegated_discovery`，1 次 MCP 调用，4 次模型请求，`simulated=true`，结果通过私有接口重读。
- 空候选 Run 正确报告“模拟空结果”而不编造价格；明确关键词 Run 返回“彩色铅笔套装”12.8 元并标记模拟。
- 第二个用户读取 Run/结果/事件均为 404；SSE 终态补读 `queued -> running -> completed`；根配置缺少密钥的首次尝试安全失败且无结果。
- 验收后删除隔离测试用户及其级联数据，项目库恢复为 0 用户/0 Run；API/shopping-mcp 已停止，数据库卷保留。补齐前次的 API/Worker/PostgreSQL 缺口。

## 013 网页工作台

- 网页已提供登录/注册、私有对话、购物任务与条件版本、`shopping_agent` Run、取消、SSE 状态同步和受限结果展示；真实 Worker/MCP completed、刷新恢复和双用户隔离已验收。
- 真实 Chrome 152 登录保留账号 `web013run` 后显示保留对话、任务和 completed Run；点击“退出”后回到认证页，刷新后仍为登录页，`/api/me` 返回 401，私有任务文本不再出现。
- 独立 HTTP 客户端补读 completed Run 的 SSE：`after=0` 返回 queued/running/completed，`after=2` 仅终态，`after=3` 空流关闭；JSON 事件补读一致。
- 测试账号、对话、任务和两个 Run 按报告保留；一次性服务端会话已删除；数据库卷未删除；API、Vite、Chrome 和 shopping-mcp 已停止。

## 014 已选购物任务多轮对话

- 新增 `POST /api/conversations/{conversation_id}/tasks/{task_id}/turns`、0009 消息/Run 关联迁移和 0010 assistant 部分唯一索引；网页增加任务对话面板。
- 真实两轮链路通过：第 1 轮追问生成 assistant 消息；第 2 轮“25 人，预算 200 元，买彩色铅笔”生成新 revision 和 Run，独立 Worker 经真实 DeepSeek 委派 real shopping-mcp 1 次并 completed，assistant 消息与结果一致。
- 幂等同键重试返回原 Run/assistant，同键异内容 409；第二账号读取任务、Run、消息、结果均为 404；浏览器刷新后 4 条消息、REV 3 和两个 completed Run 与刷新前一致。
- 模型决策解析增加容错和一次有界纠正重试，Worker 失败摘要保留真实 LLM 错误；0010 已完成降级/重升级，`alembic check` 无新增操作。Python `51 passed`，前端 lint/build 通过。
- 本轮隔离测试账号已删除，013 保留账号与数据库卷未删除；详见 [014 报告](reports/014-shopping-task-chat-report.md)。

## 015 教师奖品采买候选与结构化方案

- 0011 迁移创建 `shopping_candidates`、`shopping_plans` 和 `shopping_plan_items`；候选以 `(run_id, product_id)` 去重，方案以 `run_id` 唯一，均绑定 owner、task、revision 和 run。
- `shopping_agent` 完成后在同一终态事务中写入候选快照、服务端复算方案、Run 结果、assistant 消息和 completed 事件；`GET /api/runs/{run_id}/shopping-artifacts` 按 owner 读取，越权统一 404。
- 规划使用 `Decimal`、CNY、包装可分份数和 `ceil(people / distributable_units)`；未知运费、税费和优惠不当作零，结果标记 `unknown_fees=true`。有效方案回答由服务端按已校验数量和金额生成。
- 真实验收：教师奖品任务由真实 DeepSeek、Java `shopping-mcp`、独立 Worker 和 PostgreSQL 完成；1 次 MCP、4 次模型请求、1 次委派，保存 2 个模拟候选。REV 1 方案为贴纸 1 包、覆盖 25 人、总额 `6.90`、余量 `193.10`；预算改为 180 元生成 REV 3，旧 REV 1 仍可读取。REV 2 的人数与目标文本冲突，Agent 返回 clarification 且未写入方案。
- Python 全量 `57 passed`、Java `6 passed`、前端 build、Ruff、compileall、Alembic check 均通过；新增终态事务、重放幂等、候选方案权限测试，真实第二账号读取 artifacts 返回 404。真实来源仍为 Java 模拟商品，不代表实时库存、报价或下单。

## 每次读取最新 GitHub 时的检查方式

1. 明确默认分支或用户指定分支，读取最新提交 SHA，并与本页基线比较。
2. 读取 `CLAUDE.md`、文档导航、本页、相关执行任务和报告，再检查变更代码与可用 CI 结果。
3. 将计划、已实现、已验证、未验证和阻塞分别说明。源码和可复核结果优先于旧进度声明；新用户决定优先于历史任务范围。
4. 依据当前目标与依赖推荐一个可验收的小任务，说明它解决什么、为何现在做及完成标准。
5. 讨论确定后生成 AI 执行文档；实施者完成后更新报告与本页，写明审查过的代码提交。
6. 若代码已前进而进度页未更新，先指出差异，不能机械重复上一轮计划。

用户每次主动请求查看仓库时执行上述流程；没有自动轮询或后台监控。

## 当前状态与下一步

截至 2026-11-03，010 已完成受控购物执行、结果持久化、真实 PostgreSQL 0007 迁移，以及真实 DeepSeek→shopping-mcp→PostgreSQL 闭环与外部调用中断恢复验收；外部调用不承诺 exactly-once。011 已完成项目专用 PostgreSQL 默认可复现、单源配置收敛、旧卷角色对齐、0007 迁移和 down/up 持久化验证。012 已完成主从 Agent 代码、0008 迁移、真实 API/Worker/PostgreSQL 闭环、用户隔离和 SSE 终态补读。013 已完成网页认证、私有对话/任务、Run 排队、SSE 状态展示、真实 Worker/MCP 结果、双用户隔离、登出后刷新和独立 SSE 终态补读。014 已完成已选购物任务的两轮对话、条件修订、assistant 消息唯一持久化、真实 Worker/DeepSeek/MCP 执行、幂等、跨账号隔离和浏览器刷新重读。

[001](vibe%20coding/001-llm-connection.md)至[014 已选购物任务的多轮对话与助手消息持久化](vibe%20coding/014-shopping-task-chat.md)均已完成；013 的登出刷新、独立 SSE 和 014 的两轮真实闭环均有报告证据。015 已完成候选快照与服务端复算方案，016 已完成不可变方案调整，017 已完成目标一致性与 Run 前门禁并跑通真实 DeepSeek/MCP 新 Run 闭环。

## 2026-11-02 架构讨论归档

在仓库 `8459e40` 基础上记录 Agent 分类、协作、Tools 与 MCP、RAG、意图识别讨论，入口见 [设计索引](design/README.md)。此段是当时设计归档；目前 P1 的 001–003 与 P2 的 004–008 已提交，私有对话、任务和条件版本隔离已验证；完整 Agent、自动意图路由和 RAG 尚未实现。

PostgreSQL + pgvector 为推荐检索基线；分块和召回数为实验起点，Embedding 和重排型号及分类阈值仍需评估。当时的讨论只更新设计与导航；之后 002–008 均已提交，验收边界见各报告。仓库自带 PostgreSQL 17 Compose 未配置 pgvector；用户其他实例的扩展状态尚未核对。
