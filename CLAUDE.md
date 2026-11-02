# CLAUDE.md

## 项目概况

生活采买智能体：React 网页 + Python 主后端 + 三个 Java 服务。当前处于**第 0 阶段：项目初始化**。

## 当前阶段约束

- 只完成初始化；**在没有新任务前不要继续实现业务**，也不要因为框架能启动就接着实现教师奖品采买链路。
- 后端只有一个 API：`GET /api/health`。不要新增聊天、任务、用户、商品、投稿或订单接口。
- 网页只有项目名称、初始化说明和真实健康检查按钮。不要新增路由、聊天界面、管理后台、商品卡片或模拟业务列表。
- Java 服务只有启动类和 `/actuator/health`。不要创建 `/mcp` 路由、工具注册、Entity、Mapper、Repository、Service 或 Controller。
- 不创建模拟商品数据、假对话或“演示 Agent”；不为了数量添加检查空类存在的测试。
- 健康检查只代表进程可响应，**不代表数据库、LLM 或 MCP 已接通**。

## 已确定的技术方向

- Python 是主系统，一个 uv 工程；未来 API 与 Worker 共享，不为每个 Agent 建服务。
- Python 使用 FastAPI，LangGraph 只装基础依赖（当前无图、无检查点）。
- 网页使用 React + TypeScript + Vite。
- 三个 Java 服务（shopping / travel / local-life）用于模拟外部 MCP 服务，验证通用接入机制，后续可接入其他 MCP；当前只是 Spring Boot 骨架。
- 主体为一个仓库、多个子工程；根目录不建立 npm 或 uv workspace，不引入 Nx、Turborepo。

## 包管理边界

| 子工程 | 管理方式 | 锁文件 / 版本依据 |
| --- | --- | --- |
| `backend/` | uv | `pyproject.toml`、`uv.lock`、`.python-version` |
| `web/` | npm | `package.json`、`package-lock.json`、根 `.nvmrc` |
| `mcp-services/` | Maven Wrapper | 父子 `pom.xml`、`mvnw`、`.mvn/wrapper/` |

- 不提交 `.venv/`、`node_modules/`、`dist/`、`target/`、实际 `.env` 或日志。
- 不忽略 `uv.lock`、`package-lock.json` 或 Maven Wrapper 必要文件。
- 不新增远程仓库、不自动提交或推送。

## 目录职责

- `backend/src/life_agent/api/`：HTTP 路由。
- `backend/src/life_agent/core/`：应用配置。
- `backend/src/life_agent/agents/`：未来主协调、信息发现、采买规划、出行子图；当前仅 README 和空的 `__init__.py`。
- `backend/src/life_agent/tools/`：未来 MCP、地图、搜索、知识检索；当前无客户端或工具函数。
- `backend/src/life_agent/modules/`：未来业务模块；当前无业务类。
- `backend/src/life_agent/db/`、`worker/`：预留说明，无实现。
- `web/src/api/health.ts`：唯一的前端请求封装。
- `web/src/components/`、`features/`：预留目录。
- `mcp-services/`：Spring Boot 4.1.2 多模块骨架，JDK 21。

## 启动与检查

```bash
# backend
cd backend && uv sync --locked
uv run ruff check src
uv run python -m compileall -q src
uv run uvicorn life_agent.main:app --host 127.0.0.1 --port 8000

# web
cd web && npm ci && npm run lint && npm run build
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort

# java
cd mcp-services && ./mvnw -B -ntp verify
./mvnw -pl shopping-mcp spring-boot:run
```

环境：Python 3.12、Node 22（Vite 8 要求 `^20.19.0 || >=22.12.0`）、JDK 21、Spring Boot 4.1.2。详细端口与说明见 `docs/guides/development.md`。

## 文档驱动的后续工作

先读 [文档导航](docs/README.md)、[当前进度](docs/progress.md)，再读用户本次指定的 [AI 执行任务](docs/vibe%20coding/README.md)。每个具体实施步骤先有编号任务文档，完成后有对应报告与进度更新。当前阶段约束描述初始化范围；收到明确的新任务后，以新任务确定的范围为准，不把旧初始化文档当作永久禁止业务开发的规则。

路线图和初始设计包是参考，不自动执行其中所有阶段；000 为已执行历史任务。核对最新代码后再判断状态，区分“规划”“已实现”“已验证”。本次只整理文档，下一业务任务仍待讨论。
