# 生活采买智能体

基于大语言模型与 MCP 的多场景生活服务智能体，围绕日常采买、美食发现、出行规划和经营采购，提供有来源、可调整的推荐方案。Java 服务用于模拟外部 MCP、验证接入方式，为后续扩展其他 MCP 服务做准备。

**当前阶段：P1 最小能力验证已完成，P2 待执行。** 001–003 的报告记录了 DeepSeek 普通文本、Python—Java 模拟 MCP 和模型驱动的只读工具调用闭环。下一步是 [004 账号认证与会话基础](docs/vibe%20coding/004-auth-foundation.md)；目前仍无完整 Agent、登录或业务功能。

## 当前实现边界

- **Python 主后端**：FastAPI，仅提供 `GET /api/health` 健康检查；已有 DeepSeek 适配器、通用 MCP 客户端、一次调用上限的工具循环与独立命令行检查脚本；LangGraph 尚无状态图或 Agent。
- **网页**：React + TypeScript + Vite，只展示项目名称、初始化说明和“检查后端连接”按钮。
- **Java 服务**：shopping-mcp 已提供 Streamable HTTP `/mcp` 与只读模拟商品查询；travel-mcp、local-life-mcp 仍只有健康检查骨架。
- **数据库**：`infra/compose.yaml` 可单独启动 PostgreSQL；Python 与 Java 本轮都不连接数据库。
- **未实现**：网页模型对话、完整 Agent、Worker、登录与用户隔离、账号/任务/投稿/订单等业务模块。

## 技术栈与版本

| 子工程 | 技术 | 本轮实际版本 | 版本依据 |
| --- | --- | --- | --- |
| `backend/` | Python + FastAPI + LangGraph，uv 管理 | Python 3.12.13；FastAPI 0.162.0；LangGraph 1.2.19；uvicorn 0.54.0 | `pyproject.toml`、`uv.lock`、`.python-version` |
| `web/` | React + TypeScript + Vite，npm 管理 | Node 22.23.2；React 19.3.1；Vite 8.3.5；TypeScript 7.0.2 | `package.json`、`package-lock.json`、根目录 `.nvmrc` |
| `mcp-services/` | Java + Spring Boot，Maven Wrapper | JDK 21.0.12；Spring Boot 4.1.2；Maven Wrapper 3.9.16 | 父子 `pom.xml`、`.mvn/wrapper/` |

Node 22.23.2 满足 Vite 8 的 `^20.19.0 || >=22.12.0` 要求；本轮沿用本机已安装的受支持版本，而非文档建议的 Node 24。当前 create-vite 模板使用 **Oxlint** 作为 lint 工具（`npm run lint`），项目保留了模板自带的 lint 配置。

## 项目目录

| 路径 | 职责 |
| --- | --- |
| `backend/` | Python 主系统，一个 uv 工程；未来 API 与 Worker 共享 |
| `backend/src/life_agent/main.py` | FastAPI 应用入口 |
| `backend/src/life_agent/core/config.py` | `pydantic-settings` 应用配置 |
| `backend/src/life_agent/api/` | API 路由，当前只有健康检查 |
| `backend/src/life_agent/agents/` | 主协调、信息发现、采买规划、出行子图预留目录 |
| `backend/src/life_agent/tools/` | 已有通用 MCP 客户端；地图、搜索、知识检索预留 |
| `backend/src/life_agent/modules/` | 账号、会话、任务、投稿、方案等业务模块预留目录 |
| `backend/src/life_agent/db/` | 数据库接入预留说明（无模型、无迁移） |
| `backend/src/life_agent/worker/` | 后台执行器预留说明（无运行入口） |
| `web/` | React + TypeScript + Vite 网页 |
| `mcp-services/` | Maven 父工程与三个 Spring Boot 子模块 |
| `contracts/` | 已有 shopping MCP 工具契约；REST、SSE 与卡片协议预留 |
| `infra/` | 可选本地 PostgreSQL 与本地环境模板 |
| `mobile/android/` | Android 扩展端说明（本轮不生成工程） |
| `docs/` | 项目定位、设计、AI 执行任务、进度、报告与指南分层管理 |

## 快速开始

三个子工程可独立启动。完整步骤与常见问题见 [开发指南](docs/guides/development.md)。

### 1. Python API

```bash
cd backend
uv sync --locked
uv run uvicorn life_agent.main:app --host 127.0.0.1 --port 8000
```

验证：<http://127.0.0.1:8000/api/health>、<http://127.0.0.1:8000/docs>

### 2. 网页

```bash
cd web
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 <http://127.0.0.1:5173>，点击“检查后端连接”。API 未启动时页面仍能打开并显示真实的失败状态。

### 3. Java 服务（可选，独立启动）

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
# 另外两个模块：travel-mcp、local-life-mcp
```

### 4. 可选的本地 PostgreSQL

```bash
cp -n infra/.env.example infra/.env
docker compose --env-file infra/.env -f infra/compose.yaml up -d
docker compose --env-file infra/.env -f infra/compose.yaml ps
```

本轮任何应用都不连接该数据库。

## 端口

| 服务 | 地址 | 健康检查 |
| --- | --- | --- |
| 网页（Vite 开发服务器） | <http://127.0.0.1:5173> | 页面可打开 |
| Python API | <http://127.0.0.1:8000> | `/api/health`、`/docs` |
| shopping-mcp | <http://127.0.0.1:8101> | `/actuator/health` |
| travel-mcp | <http://127.0.0.1:8102> | `/actuator/health` |
| local-life-mcp | <http://127.0.0.1:8103> | `/actuator/health` |
| PostgreSQL（可选） | `127.0.0.1:5432` | 容器自身 `pg_isready` |

所有服务默认只绑定回环地址，不对外网开放。

## 开发文档

- [文档导航](docs/README.md)
- [项目定位与主线](docs/overview/project.md)
- [开发路线图](docs/roadmap.md)
- [当前进度](docs/progress.md)
- [001 模型连通报告](docs/reports/001-llm-connection-report.md)
- [002 MCP 接入报告](docs/reports/002-mcp-integration-report.md)
- [003 工具调用报告](docs/reports/003-llm-mcp-tool-loop-report.md)
- [004 账号认证执行任务](docs/vibe%20coding/004-auth-foundation.md)与[报告](docs/reports/003-llm-mcp-tool-loop-report.md)
- [Claude / Codex 执行任务](docs/vibe%20coding/README.md)

- [开发说明：安装、启动、检查与常见问题](docs/guides/development.md)
- [初始化报告：实际完成项与验证结果](docs/reports/000-initialization-report.md)
- [项目初始设计包](docs/design/生活采买智能体_项目初始设计包.md)
- [课题项目计划书](docs/overview/生活采买智能体_课题项目计划书.md)

## 明确留到下一阶段

LangGraph 状态图、多 Agent、登录/会话/任务/SSE、数据模型与迁移、投稿与知识库、地图/搜索/天气、Android 工程、订单与支付，以及完整页面设计。详见 `docs/guides/development.md` 的“后续阶段”一节。
