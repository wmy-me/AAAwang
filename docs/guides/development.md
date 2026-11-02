# 开发说明

本文描述现有工程的安装、启动和验证方式。业务功能尚未开发；P1 已完成模型普通文本、模拟 MCP 查询及一次模型工具调用闭环。

## 1. 各子工程的职责与边界

| 子工程 | 职责 | 当前实现边界 |
| --- | --- | --- |
| `backend/` | Python 主系统 | FastAPI 健康检查、DeepSeek 检查、通用 MCP 客户端及有限工具循环；LangGraph 仅安装依赖 |
| `web/` | React 网页 | 初始化说明页与真实健康检查按钮；Vite 开发代理 |
| `mcp-services/` | 三个 Java 服务 | shopping 提供模拟 MCP 查询；travel 与 local-life 保持健康检查骨架 |
| `infra/` | 本地基础服务 | 可选 PostgreSQL 容器；应用不连接 |
| `contracts/` | 协议契约 | 包含 shopping 模拟 MCP 工具输入输出约定 |
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

### 3.2 DeepSeek 连通检查

在 `backend/.env` 中设置 `LLM_API_KEY`。密钥只保留在本机，不要写入命令、对话、报告或提交。模型默认使用已由官方文档确认的 `deepseek-flash` 和 `https://api.deepseek.com`。

```bash
cd backend
uv run python scripts/check_llm.py
```

该命令发送一次非流式普通文本请求，超时为 60 秒且自动重试关闭。缺少配置、认证失败、模型不存在、超时、连接失败或空响应时返回非零退出码。它不验证工具调用、结构化输出、流式响应、MCP 或 Agent。

### 3.3 MCP 联调

先启动 Java 模拟服务：

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
```

另一个终端使用 Python 官方 SDK 完成初始化、发现与一次查询：

```bash
cd backend
uv run python scripts/check_mcp.py --service shopping
```

默认配置位于 `MCP_SERVICES`，按服务 ID保存 URL、`streamable_http` 传输、超时和启用状态。读取配置或启动 API 不会建立连接。shopping-mcp 只绑定回环地址，MCP 端点为 `/mcp`，模拟契约见 `contracts/mcp/`。

### 3.4 LLM 与 MCP 工具闭环

先按 3.3 启动 shopping-mcp，并在 `backend/.env` 配置 `LLM_API_KEY`：

```bash
cd backend
uv run python scripts/check_tool_loop.py --service shopping \
	--prompt "我想买一盒彩色铅笔，单价不超过15元。请查询模拟商品后回答。"
```

成功必须包含真实结构化 tool_call、一次 MCP 调用和基于结构化结果的后续模型回答。脚本会核对模拟来源、候选名和价格；模型直接回答会返回失败，不能作为闭环证据。

### 3.5 网页

```bash
cd web
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 <http://127.0.0.1:5173>，点击“检查后端连接”。Vite 将 `/api` 代理到 `http://127.0.0.1:8000`，保留路径前缀。该代理仅用于开发，不代表生产部署完成。

### 3.6 Java 服务

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
./mvnw -pl travel-mcp spring-boot:run
./mvnw -pl local-life-mcp spring-boot:run
```

分别访问 `http://127.0.0.1:8101/actuator/health`、`8102`、`8103`。shopping 另有 `/mcp`；其余服务仍只有健康端点。

### 3.7 可选 PostgreSQL

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
uv run pytest -q
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

shopping-mcp 包含查询边界和 Origin 过滤测试；另外两个模块仍无业务测试。

## 6. 常见问题

| 现象 | 排查与处理 |
| --- | --- |
| `uv sync --locked` 提示锁文件过期 | 不要手工改锁文件；在确认依赖变更后运行 `uv lock`，再提交 `uv.lock` |
| 模型检查提示缺少 `LLM_API_KEY` | 将 DeepSeek API Key 写入被忽略的 `backend/.env`；不要写入 `.env.example` |
| 模型检查认证、模型或超时失败 | 分别核对本地密钥、DeepSeek 当前模型 ID、网络和 `LLM_TIMEOUT_SECONDS`；脚本不会自动重试 |
| MCP 检查初始化失败或超时 | 确认 shopping-mcp 已启动、8101 未被占用，并核对 `MCP_SERVICES` 中的 URL 与超时 |
| 工具闭环提示模型未调用工具 | 使用明确要求查询模拟商品的问题；这不是成功证据，脚本不会无界重试 |
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
- `backend/src/life_agent/tools/` 中 maps、search、knowledge 仍为预留；mcp 已实现通用客户端
- `backend/src/life_agent/modules/`、`db/`、`worker/`
- `backend/tests/`
- `web/src/components/`、`web/src/features/`
- `mobile/android/`

尚未接通：

- Python 与 DeepSeek、shopping-mcp 的独立检查入口已实现。PostgreSQL、地图/搜索仍未连接。
- shopping-mcp 已有标准协议和一个只读模拟工具；travel 与 local-life 没有 MCP。
- LLM 已通过独立有限执行器根据 schema 调用一个只读 MCP 工具；尚未接入 HTTP 聊天、LangGraph 或 Agent。
- 网页没有聊天、任务、投稿、方案等业务页面。

## 9. 后续阶段

Agent 状态图、登录/会话/任务/SSE、ORM 与迁移、投稿与知识库、地图/搜索/天气、商品比较与预算、出行规划、Android 工程、订单/预订/支付，以及完整页面设计与全应用容器化。

这些能力需要收到新的开发任务后再实施。
