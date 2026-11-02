# 004：账号认证与会话基础

- 状态：待执行；本文件是 AI 执行任务，尚无实现与验收报告
- 所属阶段：P2 任务与对话基础的第一步
- 起始分支和提交：`main` / `bd4dafad8a47c9fc02086c947255c1856645de95`；执行前重新核对 HEAD，保留后续已有改动
- 前置：P1 的 001、002、003 已提交，分别有执行报告
- 对应报告：`docs/reports/004-auth-foundation-report.md`
- 目标：建立 Python API 的最小账号、持久化会话及受信用户身份，为后续私有资源归属校验提供基础

## 1. 先读和确认

先读根 `CLAUDE.md`、[任务规则](README.md)、[当前进度](../progress.md)、[路线图](../roadmap.md)、[项目定位](../overview/project.md)，再核对 `backend/src/life_agent/main.py`、`api/router.py`、`core/config.py`、`db/`、`modules/`、`backend/pyproject.toml`、`infra/compose.yaml` 和现有测试。发现源码已前进时依据最新代码调整任务并在报告说明差异。

当前 API 仅有公开的 `GET /api/health`；PostgreSQL Compose 可选但主程序尚未连接数据库。003 是命令行里的共享只读模拟查询，不提供登录、用户会话或私有任务。不要将“模型能调用工具”当作已经具备身份隔离。

## 2. 本轮范围

在 Python 主后端新增账号和登录会话的最小纵向链路，推荐接口：

| 接口 | 结果 |
| --- | --- |
| `POST /api/auth/register` | 创建普通用户；对重复标识、非法输入有明确结果 |
| `POST /api/auth/login` | 校验凭据并签发新的服务端会话 Cookie |
| `POST /api/auth/logout` | 服务端吊销当前会话并清理 Cookie |
| `GET /api/me` | 根据受信认证上下文返回自己的最少必要信息；匿名请求拒绝 |

仅创建这一步所需的用户、会话数据表和迁移；具体表名与字段在实现前确定并更新契约。使用已有 PostgreSQL Compose 作真实持久化验证，数据库连接和迁移由 Python 工程管理，不让 Java 模拟服务维护用户登录。将“当前用户”作为 FastAPI 依赖或同等明确边界，后续资源服务从该上下文取用户 ID，不能接受请求体、模型或 MCP 响应声称的用户 ID 作为授权依据。

Cookie 会话应有不可预测标识、服务端到期和吊销机制；在存储泄露风险下避免保存可直接重放的完整会话秘密。密码使用成熟的慢哈希算法（优先 Argon2id，按实际依赖与环境核对参数），不存明文、可逆加密或快速摘要。配置本地 HTTP 开发和 HTTPS 部署所需 Cookie 属性：HttpOnly、SameSite、Secure、Path 等明确记录；不将凭据放在浏览器 localStorage。对于注册、登录、退出和以后使用 Cookie 的状态变更接口，落实与同源代理部署方式匹配的 CSRF 防护并测试跨站请求，不能把 SameSite 单独当成普遍充分的防护。后端要避免错误回显密码、会话令牌或数据库连接串。

本轮只做普通用户认证基础。不加入完整角色后台、邮箱验证码、密码重置、第三方登录、网页登录页、任务/会话/方案表、聊天、SSE、Worker、LangGraph 图或商品业务。保留公开健康接口与 P1 三项命令行检查；API 导入和健康接口不因模型密钥或 Java 停服而失败。

## 3. 执行顺序

1. 选定与当前 Python 版本兼容的数据库驱动、ORM/迁移和密码库，锁定依赖；明确数据库 URL 环境模板，凭据只在本地文件或环境中使用。
2. 建立最小数据库模型、迁移、连接生命周期、账号与会话存取。迁移可从空数据库重复执行；不要依赖自动建表替代正式迁移。
3. 实现注册、登录、登出、`/me` 与受信用户依赖。服务端处理重复注册、弱/非法输入、错误密码、过期与已吊销会话；响应不暴露密码哈希或会话秘密。
4. 实现 Cookie 属性与 CSRF 策略，在 API 和开发代理的实际部署方式下检查。若本地 HTTP 与生产 HTTPS 需要不同配置，明确失败条件，避免把开发配置默认为生产安全。
5. 编写聚焦接口及数据层测试；使用真实 PostgreSQL 进行一次迁移、注册、登录、进程/客户端重新连接后的身份恢复、登出与到期验证。敏感数据脱敏记录。
6. 更新 REST 契约、配置模板、运行指南、进度和执行报告。完成后停止，私有资源的数据模型与跨用户访问测试放在下一编号任务。

## 4. 验收标准

| 检查 | 可观察结果 |
| --- | --- |
| 注册与持久化 | 两个不同用户能注册，重复标识被拒；数据库只保存密码哈希，重启后用户仍存在 |
| 登录与注销 | 正确密码建立新会话；错误密码不能登录；登出后原 Cookie 不再能访问 `/me` |
| 身份边界 | 匿名和过期会话访问 `/me` 被拒；A 的 Cookie 返回 A，B 的 Cookie 返回 B；请求体中伪造 user_id 不改变认证身份 |
| Cookie 与 CSRF | 实际响应 Cookie 属性与配置匹配；跨站状态变更请求被阻断；本地开发代理正常使用 |
| 迁移与故障 | 空库迁移和重复运行可复核；数据库不可用时认证请求失败明确、不会误判为匿名成功；公开健康接口及 API 导入可按设计工作 |
| 回归 | Python 既有 001–003 聚焦测试、静态检查继续通过；未修改 Java 和网页时无需重复无关构建 |

两个账户访问各自 `/me` 仅证明账号会话没有混用，**不能宣称已经完成私有任务、对话、方案的跨用户隔离**。首个私有资源出现时必须对读取、修改、取消、列表、SSE 和后台执行分别做归属检查及双用户越权验证；不能只在前端隐藏入口。

若数据库、迁移或浏览器安全策略尚未验证，报告未验证项并标记部分完成或受阻。测试替身不能替代真实 PostgreSQL 持久化证据。不要创建生产默认账号或把示例口令写进提交。

## 5. 完成后与停止条件

创建 `docs/reports/004-auth-foundation-report.md`，记录实际起始提交、依赖与迁移版本、命令、真实数据库及替身测试结果、安全配置取舍、未验证项；同步 `docs/progress.md`、[任务索引](README.md)、根 README 和开发指南。达到验收才把 004 改为已完成。

完成后停止。下一任务再引入私有会话/任务等资源与完整的跨用户读写隔离；P3 采买 Agent、P5 RAG 与 P6 出行继续按路线图另立任务。

## 资料入口

- [OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP 会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet)
- [OWASP CSRF 防护](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [FastAPI 安全教程](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)

资料是实施前核对的入口；接口与配置以执行时实际验证为准。
