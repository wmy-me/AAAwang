# 开发说明

本文只描述第 0 阶段（项目初始化）的实际环境、安装、启动和验证方式。业务功能尚未开发。

## 1. 各子工程的职责与边界

| 子工程 | 职责 | 当前实现边界 |
| --- | --- | --- |
| `backend/` | Python 主系统 | FastAPI 入口、配置读取、`GET /api/health`；LangGraph 仅安装依赖 |
| `web/` | React 网页 | 初始化说明页与真实健康检查按钮；Vite 开发代理 |
| `mcp-services/` | 三个 Java 服务 | Spring Boot 启动类、Actuator 健康检查；无 MCP 协议与业务接口 |
| `infra/` | 本地基础服务 | 可选 PostgreSQL 容器；应用不连接 |
| `contracts/` | 协议契约 | 仅存放约定说明 |
| `mobile/android/` | Android 扩展端 | 仅说明，未生成工程 |

## 2. 实际环境与版本

本轮在 **原生 Linux（Ubuntu 内核 5.15）** 上执行，不是 WSL2。原执行文档按 Windows + WSL2 编写；工具链与命令一致，差异只存在于宿主与浏览器访问方式，见第 7 节。

| 工具 | 实际版本 | 备注 |
| --- | --- | --- |
| git | 2.34.1 | 用于仓库版本控制 |
| uv | 0.11.32 | Python 工程与依赖管理 |
| Python | 3.12.13 | uv 管理的 CPython，记录在 `backend/.python-version` |
| Node.js | 22.23.2 | 满足 Vite 8 的 `^20.19.0 || >=22.12.0` |
| npm | 10.9.8 | 网页依赖管理 |
| Java | OpenJDK 21.0.12 (Temurin) | `javac` 同版本 |
| Maven | 3.9.16 | 仅用于生成 Wrapper；日常使用 `./mvnw` |
| Docker | 29.6.2 | 可选 PostgreSQL |
| Docker Compose | v5.3.1 | 可选 PostgreSQL |

依赖安装位置与锁文件：

- Python：`backend/.venv/`（不提交），锁定于 `backend/uv.lock`。
- 网页：`web/node_modules/`（不提交），锁定于 `web/package-lock.json`；Node 主版本记录在 `.nvmrc`。
- Java：本机 Maven 仓库（`~/.m2`），版本由父 `pom.xml` 与 Maven Wrapper 固定。

## 3. 启动命令与工作目录

### 3.1 Python API

```bash
cd backend
uv sync --locked
uv run uvicorn life_agent.main:app --host 127.0.0.1 --port 8000
```

- 健康检查：<http://127.0.0.1:8000/api/health>
- 接口文档：<http://127.0.0.1:8000/docs>

配置可选：`cp backend/.env.example backend/.env`。模板不含任何密钥；应用启动不访问模型、地图或数据库。

### 3.2 网页

```bash
cd web
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 <http://127.0.0.1:5173>，点击“检查后端连接”。Vite 将 `/api` 代理到 `http://127.0.0.1:8000`，保留路径前缀。该代理仅用于开发，不代表生产部署完成。

### 3.3 Java 服务

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
./mvnw -pl travel-mcp spring-boot:run
./mvnw -pl local-life-mcp spring-boot:run
```

分别访问 `http://127.0.0.1:8101/actuator/health`、`8102`、`8103`。每个服务只暴露 `health` 端点。

### 3.4 可选 PostgreSQL

```bash
cp -n infra/.env.example infra/.env
docker compose --env-file infra/.env -f infra/compose.yaml up -d
docker compose --env-file infra/.env -f infra/compose.yaml ps
```

停止：`docker compose --env-file infra/.env -f infra/compose.yaml down`（默认保留数据卷）。详见 `infra/README.md`。

## 4. 端口表

| 服务 | 端口 | 绑定地址 | 健康检查 |
| --- | --- | --- | --- |
| 网页（Vite） | 5173 | 127.0.0.1 | 页面可打开 |
| Python API | 8000 | 127.0.0.1 | `GET /api/health` |
| shopping-mcp | 8101 | 127.0.0.1 | `GET /actuator/health` |
| travel-mcp | 8102 | 127.0.0.1 | `GET /actuator/health` |
| local-life-mcp | 8103 | 127.0.0.1 | `GET /actuator/health` |
| PostgreSQL（可选） | 5432 | 127.0.0.1 | 容器 `pg_isready` |

## 5. 如何验证

### 5.1 Python 静态检查与启动

```bash
cd backend
uv sync --locked
uv run ruff check src
uv run python -m compileall -q src
uv run python -c "from life_agent.main import app; print(app.title)"
uv run uvicorn life_agent.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","service":"life-buy-agent-api"}
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/docs
# 200
```

### 5.2 网页检查、构建与代理

```bash
cd web
npm ci
npm run lint
npm run build
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

API 同时运行时，另开终端验证代理：

```bash
curl http://127.0.0.1:5173/
curl http://127.0.0.1:5173/api/health
```

浏览器中点击“检查后端连接”应显示成功；关闭 API 后再次点击应显示失败，而不是固定显示“全部服务正常”。

### 5.3 Java 构建与健康

```bash
cd mcp-services
./mvnw -B -ntp verify
./mvnw -pl shopping-mcp spring-boot:run
curl http://127.0.0.1:8101/actuator/health
```

另外两个模块按同样方式验证。没有业务测试，因此“构建成功”不等于“业务测试通过”。

## 6. 常见问题

| 现象 | 排查与处理 |
| --- | --- |
| `uv sync --locked` 提示锁文件过期 | 不要手工改锁文件；在确认依赖变更后运行 `uv lock`，再提交 `uv.lock` |
| Python 3.12 不存在 | 执行 `uv python install 3.12`；项目已通过 `.python-version` 固定版本 |
| `npm ci` 失败或很慢 | 检查 `npm config get registry` 与网络；不要删除 `package-lock.json` 后盲目重装 |
| 5173 / 8000 / 8101–8103 被占用 | `ss -ltnp \| grep <端口>` 或 `lsof -i :<端口>` 找到进程；只结束自己启动的进程，或换端口并同步代理配置 |
| 网页健康检查失败 | 确认 API 在 8000 端口运行；检查 `vite.config.ts` 的代理目标；浏览器开发者工具查看请求 |
| `npm run build` 失败 | 先运行 `npm run lint` 与 `npx tsc -b` 查看具体 TypeScript 错误 |
| Maven 首次构建下载慢 | 首次会下载 Maven 3.9.16 与 Spring Boot 依赖到 `~/.m2`；后续构建使用缓存 |
| `./mvnw` 无执行权限 | `chmod +x mcp-services/mvnw`；该文件应保留 LF 换行 |
| Docker 不可用 | 跳过 PostgreSQL；不影响 Python、网页和 Java 骨架的启动验证 |
| 5432 已被本机 PostgreSQL 占用 | 停止本机实例或修改 `infra/compose.yaml` 的映射端口；不要直接扩大绑定地址 |

## 7. WSL2 与 Windows 浏览器

执行文档假设 Windows + WSL2。本轮实际为原生 Linux，未涉及 Windows 宿主，因此**未在 Windows 浏览器中验证**。

后续在 WSL2 中开发时：

- 建议把仓库放在 WSL 文件系统内（例如 `~/projects/`），而不是 `/mnt/c/`，以避免文件监听和权限问题。
- WSL2 默认的 localhost 转发通常允许 Windows 浏览器访问 `http://localhost:5173`。
- 所有服务当前只绑定 `127.0.0.1`。如果本地网络模式导致 Windows 侧无法访问，先执行 `ss -ltn` 与 `curl` 在 WSL 内确认服务正常，再记录具体的网络模式与报错；**不要**未经诊断把所有服务的监听地址改为 `0.0.0.0`。
- `mvnw` 与 Python/Node 工具应在 WSL 内运行，避免 Windows 与 Linux 两套工具混用同一个依赖目录。

## 8. 预留目录与未接通项

只有说明、没有实现的目录：

- `backend/src/life_agent/agents/`（含四个子目录）
- `backend/src/life_agent/tools/`（含四个子目录）
- `backend/src/life_agent/modules/`、`db/`、`worker/`
- `backend/tests/`
- `web/src/components/`、`web/src/features/`
- `contracts/`、`mobile/android/`

尚未接通：

- Python 与 PostgreSQL、LLM、地图/搜索服务、三个 Java 服务均未连接。
- Java 服务没有 MCP 协议、工具注册或业务查询。
- 网页没有聊天、任务、投稿、方案等业务页面。

## 9. 后续阶段

LLM 接入与 Agent 状态图、MCP 客户端与 Java 协议层、登录/会话/任务/SSE、ORM 与迁移、投稿与知识库、地图/搜索/天气、商品比较与预算、出行规划、Android 工程、订单/预订/支付，以及完整页面设计与全应用容器化。

这些能力需要收到新的开发任务后再实施。
