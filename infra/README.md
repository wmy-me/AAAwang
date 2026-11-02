# infra/

本地可选基础服务。本轮只包含一个 PostgreSQL 容器，**不把应用容器化**。

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
| 镜像 | `postgres:17`（明确主版本，不使用 `latest`） |
| 地址 | `127.0.0.1:5432`（仅绑定回环地址） |
| 数据库 | `life_buy_agent` |
| 用户 | `life_buy` |
| 密码 | 见 `infra/.env` 中的示例值，仅限本地开发 |

命名数据卷：`life-buy-agent-postgres-data`。容器健康检查使用 `pg_isready`。

## 停止

```bash
docker compose --env-file infra/.env -f infra/compose.yaml down
```

`down` 默认保留命名数据卷。只有明确需要清空本地数据时才使用 `down -v`。

## 当前边界

- Python 与 Java 本轮都**没有连接数据库**。
- 不创建业务表、schema、账号、种子数据或迁移脚本。
- 不安装 pgvector，不包含 Redis、对象存储、消息队列或监控服务。
- 不提供生产部署配置。
