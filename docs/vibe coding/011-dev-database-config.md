# 011：项目数据库开发环境与配置收敛

- 状态：已完成；配置收敛、旧卷角色对齐、0007 迁移和 down/up 持久化已验证；未删除卷，未修改用户其他容器和卷
- 所属阶段：P2 开发环境收敛，为 P3 和最终一键部署提供可复现基线
- 起始分支与代码提交：`main` / `87d46c26bf4cadcd5a668f0aad24c077f6c9cf85`；执行前核对最新 HEAD
- 前置：[010 购物 Run 真实闭环报告](../reports/010-shopping-run-execution-report.md)已提交；本任务不重做 010 的业务逻辑
- 对应报告：`docs/reports/011-dev-database-config-report.md`
- 决定：本项目开发默认使用**项目专用 PostgreSQL Compose + 持久化命名卷**，现有其他 PostgreSQL/MySQL 容器保持独立；用户本机数据库配置由用户本地填写，不要求在对话或提交中提供密码

## 1. 问题和先读

当前 `infra/compose.yaml` 默认启动 PostgreSQL、MySQL、Redis、MinIO；只有 PostgreSQL 为当前 Python API、Worker、Alembic 所需。仓库 `infra/.env.example` 给出的 PostgreSQL 用户/密码与 Compose 的 fallback 和 `backend/.env.example` 中 `DATABASE_URL` 不一致；文档对连接方式也有过时描述。用户已有本地服务，默认 5432/3306/6379/9000 端口易冲突；一次 `up` 不应启动无业务依赖的容器。

先核对根 `CLAUDE.md`、[开发说明](../guides/development.md)、[进度](../progress.md)、[路线图](../roadmap.md)、`infra/README.md`、`infra/compose.yaml`、两个 env 模板、`backend/src/life_agent/core/config.py`、Alembic 配置和 010 报告。检查 `.gitignore` 对本地秘密文件的覆盖。不要推断本机现有容器的数据可迁入项目，也不要删除用户卷。

## 2. 本轮实施范围

1. 项目 Compose **默认只启动 PostgreSQL**，其余 MySQL/Redis/MinIO 作为显式可选 profile 或独立可选配置，不能执行普通 `up` 就全部启动。数据库使用项目专用容器/网络/命名卷；开发宿主端口建议 `127.0.0.1:55432`，可配置且不改变用户已有服务。保持现有迁移所需 PostgreSQL 17 能力；pgvector 镜像不代表扩展已创建或 RAG 已接通。
2. **一个本地配置来源**维护项目数据库库名、用户、密码和宿主端口。推荐仓库根目录被忽略的 `.env` 与 `.env.example`，Compose 通过 `--env-file` 读取；后端在本地开发时从同一来源构造/读取连接，避免在 `infra/.env` 与 `backend/.env` 重复输入数据库密码。保留显式 `DATABASE_URL` 环境覆盖供 CI、现有脚本、隔离验收和以后容器内运行；不能因默认配置改动破坏 001–010 测试。实现者可选择可靠的启动封装或绝对路径配置加载，但必须与当前工作目录无关、避免把密码打印进命令或日志，并说明优先级。
3. 示例值、Compose 插值默认值、后端运行默认值和文档**完全一致**；若有历史已初始化的命名卷，不能假设修改 `POSTGRES_USER/PASSWORD` 会重置库内账号。检测不匹配时给出明确操作说明，不使用 `down -v` 自动清库。秘密文件加入忽略规则并确认未被 Git 跟踪。
4. 开发体验：说明从宿主 API/数据库客户端连接 `127.0.0.1:<宿主端口>`，后续容器化 API/Worker 使用 Compose 服务名 `postgres:5432`，不能把宿主 `localhost` 硬编码进容器。给出 DBeaver/DataGrip/psql 的连接参数、查看 `users/conversations/tasks/runs/run_events/shopping_run_results` 表的只读示例，以及 `alembic current`、`alembic upgrade head` 的时机。
5. 文档说明持久化和重建语义：普通 `down` 后卷保留；重装服务/换机器只有 schema 迁移，业务数据须单独备份恢复；不要把“一键启动”描述成自动同步已有数据。记录最终 P7 要补的 API、Worker、Java、网页、迁移 job 与备份任务；本轮仍允许后端、Java 在宿主开发运行，不做整个应用生产 Compose。

## 3. 验收

| 场景 | 可观察结果 |
| --- | --- |
| 配置一致 | 无需重复填写数据库密码；默认 Compose/后端示例能连接同一专用库；从不同工作目录运行时配置行为一致；显式 `DATABASE_URL` 覆盖仍有效 |
| 端口与隔离 | 现有本机 PostgreSQL 5432 与其他服务不被停止、覆盖或抢占；普通 Compose `up` 仅启动项目 PostgreSQL；可选 profile 未启用时不启动 MySQL/Redis/MinIO |
| 持久化与查表 | 空项目卷迁移到最新 head，在项目库写入一条隔离测试记录；普通 `down`/`up` 后可用数据库客户端和 API 重读；检查结束只删除测试记录，不删除项目卷 |
| 回归与安全 | Python 全量测试、Ruff、编译、锁文件、Alembic check、Compose config 检查通过；本地秘密和真实密码不提交、不显示在报告或日志 |
| 旧卷边界 | 若已有同名卷但账号不一致，报告说明如何非破坏性诊断与备份；绝不自动清除 |

若执行环境无法访问用户本机 Docker，只在可用的隔离环境验证，并把用户本机尚未验证列入报告。确实需要新账号/密码时由用户**在本地**填写，不要求在聊天里发送。需修改生产服务或清理现有数据时另行讨论，不归入本任务。

## 4. 完成后停止

提交 [011 配置收敛报告](../reports/011-dev-database-config-report.md)，同步 [进度](../progress.md)、[任务索引](README.md)、根 README、`infra/README.md` 和开发指南；说明真实项目卷是否已验证及未验证项。完成 011 后再为主从 Agent 的最小委派/网页对话制定独立任务，不因此宣称 P2 或 P7 全面完成。
