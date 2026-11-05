# 生活采买智能体（AAAwang）

一个以自然语言任务为入口的生活采买 Agent 毕业设计项目。用户可以描述采买目标，系统按当前任务与已确认条件决定直接回答、追问，或调用受控的地点与商品查询能力；候选、来源、任务版本和方案可在网页中查看与调整。

**项目状态（截至 2026-11-05）：处于 P4 阶段。** [001–021 任务](docs/vibe%20coding/README.md)已按各自范围实施并记录验收；[022 Agent 职责与包结构整理](docs/vibe%20coding/022-agent-responsibility-structure.md)已写成执行文档，尚未实施。P4 的搜索、天气与更多生活场景，以及 P5 知识检索、P6 出行规划、P7 集成交付仍在后续计划中。详见[路线图](docs/roadmap.md)与[进度记录](docs/progress.md)。

## 已实现

| 能力 | 当前范围 |
| --- | --- |
| 自然语言任务 | 已选购物任务的多轮对话、任务目标与条件版本；模型在受控能力集合中选择直答、追问、地点、商品或组合执行 |
| 动态表单 | 模型按任务提出经服务端校验的字段；目前仅开放购物任务的 `item`、`people`、`quantity`、`budget`，不是每轮必填；确认后产生新任务版本、消息和 Run |
| 候选与方案 | 查询 Java MCP 的**模拟商品**，保存候选快照；服务端复算数量、金额与预算，支持不可变方案调整及历史版本读取 |
| 真实地点查询 | 高德地图 MCP 的 `maps_text_search` 已完成真实查询；地点结果单独保存并标记来源，不当作商品报价或库存 |
| 执行与隔离 | PostgreSQL 持久化用户、任务、消息、Run、事件、表单、候选与结果；独立 Worker 负责租约、取消、fencing；SSE 推送状态，网页刷新可重读，私有资源按用户隔离 |
| Agent 与工具约束 | 已有有限的 LangGraph 购物主从委派；模型决策受能力注册、服务配置、MCP `list_tools()` 发现结果、schema 白名单和单 Run 共享预算约束 |

**数据边界：** Java `shopping-mcp` 返回演示用模拟商品及价格；高德只提供地点信息。系统当前用于查询与规划，尚无真实商品价格/库存、交易下单或支付能力。现有主从购物图不等于完整开放式多 Agent；`agents/coordinator/` 等包的职责归位属于待执行的 022。

## 技术组成

- **Python 主后端：** FastAPI、LangGraph、DeepSeek、官方 MCP Python SDK、SQLAlchemy、Alembic；API 与独立 Worker 共用一个 uv 工程。
- **网页：** React、TypeScript、Vite，提供登录、任务对话、动态表单、Run 状态、地点与购物方案展示。
- **Java 模拟 MCP：** Spring Boot 多模块；`shopping-mcp` 有只读商品查询工具，`travel-mcp` 与 `local-life-mcp` 目前只有基础骨架。Java 服务用于模拟成熟外部 MCP 的接入；Python 客户端也已接入独立的真实高德地图 MCP。
- **存储：** 项目 Compose 默认启动 PostgreSQL 17（pgvector 镜像），由 Alembic 管理当前业务表；镜像包含 pgvector 不表示 RAG 已实现。MySQL、Redis、MinIO 处于可选 profile，当前主线不依赖它们。

## 本地运行

需要 Python 3.12、uv、Node.js 22、npm、JDK 21、Docker Compose。以下命令从仓库根目录开始；API、Worker、网页与 Java 服务分别占用终端。所有真实密钥只放在被 Git 忽略的根目录 `.env`。

### 1. 配置并启动数据库

```bash
cp -n .env.example .env
docker compose --env-file .env -f infra/compose.yaml up -d postgres --wait
cd backend
uv sync --locked
uv run alembic upgrade head
```

默认 PostgreSQL 映射到宿主 `127.0.0.1:55432`。如使用现有 PostgreSQL，调整根目录 `.env` 中的 `DATABASE_URL`，按实际环境执行迁移即可；无需再启动项目 Compose。运行模型任务前设置 `LLM_API_KEY`。本地数据库、模型和服务可分别启动，但完整任务链路需要它们同时可用。

### 2. 启动 API 与 Worker

分别打开两个终端，在 `backend/` 执行：

```bash
uv run uvicorn life_agent.main:app --host 127.0.0.1 --port 8000
```

```bash
uv run python -m life_agent.worker.runner
```

API 健康检查：<http://127.0.0.1:8000/api/health>；接口文档：<http://127.0.0.1:8000/docs>。健康检查只证明 API 进程响应，不代表模型、MCP 或数据库联通。

### 3. 启动模拟商品 MCP 与网页

分别在新终端执行：

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
```

```bash
cd web
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 <http://127.0.0.1:5173> 注册或登录，创建购物任务并通过对话提出需求。项目模板的 `MCP_SERVICES` 指向本地 `shopping-mcp`。如需真实地点查询，在本地 `.env` 设置 `MAP_MCP_KEY` 并将 `MAP_MCP_ENABLED` 设为 `true`；不要将密钥写入仓库、命令或报告。地图服务目前只验证 `maps_text_search`，其他高德工具不在已验收范围内。

### 4. 基础检查

```bash
cd backend
uv run pytest -q
uv run ruff check src scripts tests
uv run alembic check
```

```bash
cd web
npm run lint
npm run build
```

```bash
cd mcp-services
./mvnw -B -ntp verify
```

历史联调与验收结果以对应[执行报告](docs/reports/)为准；这些命令不会自动验证当前机器的 DeepSeek Key 或高德 Key。

## 目录与文档

| 路径 | 用途 |
| --- | --- |
| `backend/src/life_agent/agents/` | 现有购物主从图；协调、发现、采买职责的包结构整理见 022 |
| `backend/src/life_agent/modules/` | 认证、对话、任务、能力、表单、Run、方案等业务模块 |
| `backend/src/life_agent/tools/` | 通用 MCP 客户端、地点适配器和预留工具目录 |
| `backend/src/life_agent/worker/` | 独立数据库 Worker 与 Run 执行 |
| `web/` | React 网页 |
| `mcp-services/` | Java 模拟外部 MCP 服务 |
| `infra/` | 项目本地数据库 Compose 与可选基础服务 |
| `docs/vibe coding/` | 供 Claude、Codex 等执行者读取的编号任务 |
| `docs/reports/` | 各任务的实现、真实联调和验收报告 |

从[文档导航](docs/README.md)、[路线图](docs/roadmap.md)和[任务索引](docs/vibe%20coding/README.md)查看完整规划。最近阶段的证据见 [020 能力决策与预算报告](docs/reports/020-model-capability-budget-report.md)、[021 动态表单报告](docs/reports/021-dynamic-task-forms-report.md)。

## 后续方向

先完成 [022 Agent 职责与包结构整理](docs/vibe%20coding/022-agent-responsibility-structure.md)，再按独立任务扩展搜索、天气及更多采买场景；投稿、文档解析与 RAG 检索属于 P5，出行规划属于 P6，全应用部署与论文演示属于 P7。交易、预订和支付是后续扩展，不属于当前查询规划闭环。
