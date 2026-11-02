# 004 账号认证与会话基础报告

**项目：** 生活采买智能体  
**阶段：** P2 任务与对话基础  
**执行日期：** 2026-11-02  
**任务文档基线：** `bd4dafad8a47c9fc02086c947255c1856645de95`  
**实际执行起点：** `6e4ff66d95c428d4a055af2af39f3e634c01c019`  
**完成提交：** `454fe132630d921e1d5b5cdd9d380344f2e991d3`（本次文档核对补记；实现与报告在该提交中）  
**结论：** 已完成。账号、服务端登录会话、正式迁移、Cookie/CSRF 边界和真实 PostgreSQL 持久化均已验证。

## 1. 实现与版本

| 部分 | 实际选择 |
| --- | --- |
| ORM | SQLAlchemy 2.1.6，同步请求级 Session，连接按认证请求建立 |
| PostgreSQL 驱动 | psycopg 3.3.6 binary |
| 迁移 | Alembic 1.20.1；版本 `20261102_0001` |
| 密码 | argon2-cffi 25.1.0，Argon2id：64 MiB、3 次迭代、并行度 4 |
| 会话 | 32 字节随机 URL-safe 秘密；数据库仅存 SHA-256 摘要 |

`users` 保存 UUID、规范化用户名、密码哈希、启用状态和创建时间；`login_sessions` 保存用户外键、秘密摘要、到期、吊销和创建时间。应用不自动建表，数据库 URL以 `SecretStr` 持有。

API 新增 `POST /api/auth/register`、`POST /api/auth/login`、`POST /api/auth/logout` 和 `GET /api/me`。当前用户只能从 Cookie 对应的服务端会话取得，请求体额外 `user_id` 或角色字段被拒绝。

## 2. Cookie 与 CSRF

- 本地 HTTP：HttpOnly、SameSite=Lax、Path=/、Secure=false。
- 生产：配置校验强制 Secure=true；SameSite=None 也强制 Secure=true，部署必须使用 HTTPS。
- 注册、登录和退出共同检查 Origin 与 `Sec-Fetch-Site`；恶意 Origin 或明确 cross-site 请求返回 403。
- Vite 开发代理来源 `http://127.0.0.1:5173` 和 `http://localhost:5173` 默认受信。无 Origin 的非浏览器本地客户端可使用 API。

这是一套同源代理部署策略。SameSite 只是附加防线，不作为唯一 CSRF 保护；凭据不放入 localStorage。

## 3. 真实 PostgreSQL 与代理证据

使用仓库 `infra/compose.yaml`、PostgreSQL 17、独立宿主端口 55432 和临时命名卷验收：

1. 空库 `alembic upgrade head` 成功，第二次升级无操作。
2. `downgrade base` 后可重新升级；`alembic check` 报告无新迁移操作。
3. 两个不同用户注册成功，重复用户名 409，错误密码 401。
4. 关闭首个 TestClient 后，新客户端携带原 Cookie 可恢复同一身份，证明数据和会话不依赖进程内存。
5. 数据库中密码为 Argon2id，未出现明文；会话只保存 SHA-256 摘要，不等于 Cookie 秘密。
6. 登出后旧 Cookie 与人工过期会话均返回 401。
7. 停止 PostgreSQL 后健康接口返回 200，认证注册返回安全 503，响应不含连接串。

另启动真实 Uvicorn，并通过当前 Vite `127.0.0.1:5173/api` 代理完成注册、登录、`/me`、恶意 Origin 登出 403、同源登出 204 和旧会话 401。验收后已停止本轮 Uvicorn，并通过 Compose `down -v` 删除临时数据库、网络和卷；未停止用户原有的 Vite 进程。

## 4. 自动检查

| 检查 | 结果 |
| --- | --- |
| 认证聚焦测试 | 5 passed：身份、吊销、到期、双用户、伪造字段、Cookie、CSRF、安全配置 |
| Python 全量测试 | 27 passed，包含 001–003 回归 |
| Ruff、compileall、`uv lock --check` | 通过 |
| Alembic | 重复升级、降级重建、`check` 均通过 |
| API 边界 | 健康接口保留；仅新增任务规定的四个认证接口 |
| Java 与网页构建 | 源码未修改，未重复无关构建；Vite 代理做了真实 HTTP 联调 |

## 5. 边界

- 本轮没有网页登录页、邮箱验证、密码重置、第三方登录、角色后台或默认账号。
- 尚无私有对话、任务、方案或 SSE，因此没有宣称完成这些资源的跨用户隔离。
- 首个私有资源必须分别验证读取、修改、取消、列表、SSE 和后台执行的所有权，不能接受客户端、模型或 MCP 提供的用户 ID。
- 未提供生产部署配置；生产 Cookie 要求已编码为失败条件，但实际 TLS 终止和生产域名需部署任务验证。
