# 011：项目数据库开发环境与配置收敛报告

- 执行日期：2026-11-03
- 对应任务：[011 项目数据库开发环境与配置收敛](../vibe%20coding/011-dev-database-config.md)
- 范围：开发配置、Compose 服务边界和配置加载；不重做010业务逻辑

## 1. 已实施

- 新增根目录 `.env.example`，作为本地配置模板；根目录 `.env` 为唯一推荐的本地配置来源，均不会提交到 Git。
- `infra/compose.yaml` 默认只启用项目 PostgreSQL，宿主默认端口为 `127.0.0.1:55432`，默认凭据与模板一致；MySQL、Redis、MinIO 改为 `optional` profile。
- PostgreSQL 仍使用 `pgvector/pgvector:pg17`，项目命名卷保持独立；没有删除卷、执行 `down -v` 或停止用户已有服务。
- 后端配置从仓库根目录 `.env` 加载，与当前工作目录无关；操作系统环境变量（包括显式 `DATABASE_URL`）优先于 env 文件和代码默认值。
- `backend/.env.example` 不再重复要求填写数据库密码；infra、开发指南和基础设施 README 已同步新的启动与连接方式。

## 2. 验证结果

| 检查 | 结果 |
| --- | --- |
| 默认 Compose 服务列表 | 通过，仅 `postgres` |
| `optional` profile 服务列表 | 通过，包含 `postgres`、`mysql`、`redis`、`minio` |
| Compose 配置解析 | 通过，`docker compose config --quiet` 无错误 |
| 后端配置加载 | 通过，根目录配置可从 backend 工程加载 |
| 显式 `DATABASE_URL` 覆盖 | 通过；环境变量优先于 env 文件 |
| 项目 PostgreSQL 启动 | 通过，容器健康，映射到宿主 `55432` |
| Alembic 迁移 | 通过：旧卷实际超级用户为 `life_buy`；通过容器内 Unix socket 重置其密码为根 `.env` 值后，迁移到 `20261103_0007 (head)`，`alembic check` 无新操作 |
| 普通 down/up 持久化 | 通过：写入隔离测试用户 → 普通 `down`（保留卷）→ `up --wait` → 测试用户与 Alembic 版本均保留；测试记录已删除，卷未删除 |

Compose 启动创建/复用了项目专用网络和项目命名容器；用户已有的 PostgreSQL、MySQL、Redis、MinIO 容器未被停止或修改。

## 3. 旧卷边界与后续操作

修改 Compose 中的 `POSTGRES_USER` 或 `POSTGRES_PASSWORD` 不会修改已经初始化的 PostgreSQL 数据卷。2026-11-03 的实际诊断结果：

- 旧项目卷由早期模板初始化为超级用户 `life_buy`；当前根 `.env` 一度使用 `postgres`，该角色在旧卷中不存在。
- 容器内 `pg_hba.conf` 对 `127.0.0.1/32` 使用 `trust`，因此容器内连接成功不能证明 `.env` 密码正确；宿主连接走 `scram-sha-256`，旧角色密码与 `.env` 不一致时表现为认证失败。
- 旧卷 `public_tables=0`，没有业务表或 `alembic_version`，不存在需要保护的业务数据。

非破坏性修复：

1. 根 `.env` 与 `infra/.env` 的 `POSTGRES_USER` 改为 `life_buy`，宿主端口统一为 `55432`；`.env.example`、`infra/.env.example` 与 Compose fallback 的用户同步对齐为 `life_buy`。
2. 通过容器内 Unix socket 的超级用户执行 `ALTER ROLE life_buy WITH PASSWORD ...`，只更新角色密码；未删除卷、未执行 `down -v`、未改写业务表。
3. 刷新旧库的 collation 元数据，消除 collation version mismatch 警告。
4. 执行 `alembic upgrade head` 到 `20261103_0007`；`alembic check` 无新操作。
5. 写入隔离测试用户 → 普通 `down`（保留卷）→ `up --wait` → 测试用户和 Alembic 版本均保留；测试记录已删除，卷未删除。

未修改用户其他 PostgreSQL/MySQL/Redis 容器或卷。

## 4. 当前连接方式

宿主运行的 API、Alembic 或 DBeaver/DataGrip 使用根 `.env` 的 `127.0.0.1:55432`、用户 `life_buy`。未来加入同一 Compose 网络的 API/Worker 应使用服务名 `postgres:5432`、用户 `life_buy`。只读查看表可使用：

```sql
SELECT * FROM users ORDER BY created_at DESC LIMIT 20;
SELECT * FROM conversations ORDER BY created_at DESC LIMIT 20;
SELECT * FROM tasks ORDER BY created_at DESC LIMIT 20;
SELECT * FROM runs ORDER BY created_at DESC LIMIT 20;
SELECT * FROM run_events ORDER BY created_at DESC LIMIT 50;
SELECT * FROM shopping_run_results ORDER BY created_at DESC LIMIT 20;
```

迁移时机：数据库容器健康后执行 `cd backend && uv run alembic current`，确认状态后执行 `uv run alembic upgrade head`。普通 `docker compose down` 保留项目命名卷；换机器或重装服务不会自动迁移业务数据，业务数据需要单独备份恢复。

## 5. 未包含范围

011 不新增 API、Worker、Java 业务、网页对话、迁移 job 或备份任务，也不宣称 P2/P7 全面完成。这些能力仍按后续独立任务推进。
