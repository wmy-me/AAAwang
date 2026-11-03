# infra/

本地可选基础服务。本地 Compose 包含 pgvector PostgreSQL、MySQL、Redis 和 MinIO，**不把应用容器化**。

## 使用前提

Docker 与 Docker Compose 已安装。Docker 不可用不影响 Python、网页或 Java 骨架的启动验证。

## 启动

```bash
cp -n infra/.env.example infra/.env

# 校验配置（不启动容器）
docker compose --env-file infra/.env -f infra/compose.yaml config --quiet

# 启动并查看状态
docker compose --env-file infra/.env -f infra/compose.yaml up -d
docker compose --env-file infra/.env -f infra/compose.yaml ps
```

或先 `cd infra` 后省略 `-f`/`--env-file` 参数。`cp -n` 表示仅在 `infra/.env` 不存在时复制，不覆盖已有配置。

## 连接信息（本地开发默认）

| 项 | 值 |
| --- | --- |
| 镜像 | `pgvector/pgvector:pg17`（明确主版本，不使用 `latest`） |
| 地址 | `127.0.0.1:5432`（仅绑定回环地址） |
| 数据库 | `life_buy_agent` |
| 用户 | `life_buy` |
| 密码 | 见 `infra/.env` 中的示例值，仅限本地开发 |

附加服务：MySQL 使用 `127.0.0.1:3306`（root/root），Redis 使用 `127.0.0.1:6379`，MinIO API 使用 `127.0.0.1:9000`、控制台使用 `127.0.0.1:9001`（admin/admin123）。它们当前只作为本地基础设施预留，010 的 Python 后端仍只使用 PostgreSQL；Redis、MinIO 和 MySQL 尚未接入业务代码。

宿主端口可通过 `POSTGRES_PORT` 调整，命名数据卷可通过 `POSTGRES_VOLUME_NAME` 调整；默认卷为 `life-buy-agent-postgres-data`。容器健康检查使用 `pg_isready`。

## 停止

```bash
docker compose --env-file infra/.env -f infra/compose.yaml down
```

`down` 默认保留命名数据卷。只有明确需要清空本地数据时才使用 `down -v`。

## Python 迁移

容器健康后，将相同连接信息写入被忽略的 `backend/.env`，再执行：

```bash
cd backend
uv run alembic upgrade head
```

应用不会自动建表或在启动时运行迁移。

## 当前边界

- Python 认证模块连接 PostgreSQL；Java 服务不连接该数据库。
- 当前只创建用户和登录会话表，不包含默认账号或业务种子数据。
- Compose 已提供 pgvector 镜像、Redis、MinIO 和 MySQL；当前不包含应用容器、消息队列或监控服务。
- 不提供生产部署配置。
