# CLAUDE.md

## 项目概况

生活采买智能体：React 网页 + Python 主后端 + 三个 Java 服务。**P1 最小 Agent 能力验证已完成**：001 模型普通文本、002 MCP 接入和 003 最小工具调用闭环均已有实现与真实验证。

## 当前执行边界

- 依据用户指定的编号任务执行；001–013 已完成，010 的真实购物闭环与中断恢复、011 的数据库配置收敛、012 的最小主从委派端到端、013 的网页工作台与登出/SSE 均已验收；外部调用不承诺 exactly-once。不自动实施完整 Agent 或采买业务。
- 后端已有健康、认证、私有对话、手工消息、私有任务、条件版本、持久化 run、Run 事件与私有 SSE、最小 Worker 及 `shopping_agent` 决策结果接口。商品、投稿和订单接口留待后续编号任务。
- 网页已提供登录/注册、私有对话、任务条件、`shopping_agent` Run、取消、SSE 状态和受限结果工作台；不要新增自然语言伪聊天、管理后台、商品卡片或模拟业务列表。
- shopping-mcp 已提供标准 Streamable HTTP `/mcp`、`search_products` 只读模拟工具与 `/actuator/health`；travel-mcp、local-life-mcp 仍为健康检查骨架。不建设业务后台。
- 003 已复用 002 的模拟商品完成真实模型工具调用联调并保留来源标记；该有限执行器不是完整 Agent 或业务对话。
- 健康检查只代表进程可响应，**不代表数据库或 MCP 已接通，也不是 LLM 验证证据**。

## 数据保护与幂等执行规则

- 所有新增字段与有副作用的操作先读[数据保护与幂等设计规则](docs/design/security-and-idempotency.md)，在编号任务中写明敏感等级、归属权限、存储/日志/传输处理、业务唯一键、重试、并发与故障恢复，并按实际风险验证。
- 密码只用慢速加盐哈希，随机会话秘密仅存摘要；第三方密钥不进仓库、日志、模型上下文或 API 响应。确需保存可恢复令牌或敏感个人资料时另设计服务端加密与密钥管理；订单号一般作为受权限约束的业务标识，不因它是订单号就一律加密。SecretStr 不等于静态加密。
- 创建或写操作依据业务唯一键/受限幂等键、数据库唯一约束与事务决定重复请求结果；条件修改还需版本检查。Worker 失租和外部调用状态不明时拒绝迟到写入并谨慎重试，外部写入不得声称 exactly-once。旧代码的完成状态不代表未来操作自动满足本规则。

## 已确定的技术方向

- Python 是主系统，一个 uv 工程；未来 API 与 Worker 共享，不为每个 Agent 建服务。
- Python 使用 FastAPI，LangGraph 已有最小 `shopping_agent` 主从委派图（无检查点、无长期记忆，不代表完整多 Agent）。
- 网页使用 React + TypeScript + Vite。
- 三个 Java 服务（shopping / travel / local-life）用于模拟外部 MCP 服务，验证通用接入机制，后续可接入其他 MCP；目前仅 shopping 提供 MCP 工具。
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
- `backend/src/life_agent/tools/`：已有通用 MCP 客户端；地图、搜索、知识检索仍为预留。
- `backend/src/life_agent/modules/`：已有认证、私有对话、任务版本与 run 模块；其他业务模块待后续任务。
- `backend/src/life_agent/db/`：已有用户、登录会话、私有对话、消息、任务、条件版本与 run 模型及请求级会话；`worker/` 已有最小诊断 runner。
- `web/src/api/health.ts`：唯一的前端请求封装。
- `web/src/components/`、`features/`：预留目录。
- `mcp-services/`：Spring Boot 4.1.2 多模块，JDK 21；shopping 已提供只读模拟 MCP 工具。

## 启动与检查

```bash
# backend
cd backend && uv sync --locked
uv run ruff check src scripts tests
uv run python -m compileall -q src scripts tests
uv run pytest -q
uv run alembic upgrade head
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

路线图和初始设计包是参考，不自动执行其中所有阶段；000 为已执行历史任务。核对最新代码后再判断状态，区分“规划”“已实现”“已验证”。P1 的 001–003 与 P2 的 004–013 均已有实现和报告；010/012 的真实闭环以及 013 的网页登出刷新与独立 SSE 已验收，外部调用不承诺 exactly-once。完整 Agent 另行规划。

## Agent 执行与预算规则

- 新增或修改 Agent 时先读[Agent 执行与预算规则](docs/design/agent-execution-rules.md)：明确哪些职责是有界 ReAct，哪些是结构化判断或确定性校验；在编号任务中约定主从共享的模型/工具/时间/修正上限、停止原因与真实验收。P3 表格数值是提案，不自动修改 012/013。
- 图的 recursion_limit 只是兜底；取消、租约、幂等、权限、外部费用与结果有效性由服务端代码约束。012 现为最小委派图，无图检查点或多轮规划；013 仅为现有 Run 的网页入口。

## Agent、工具与知识检索设计

涉及 Agent、工具、意图路由或 RAG 时，先按任务需要阅读 [设计索引](docs/design/README.md)。专题文档记录讨论方向及待验证参数，不是要求一次性执行的任务；不要把设计输出草案当成已经发布的接口。

意图识别同时考虑领域、操作与任务关联，后端校验身份和任务版本；工具按职责筛选，MCP 通用连接与领域适配分层；RAG 使用持久化、可见性与内容版本过滤。分块长度、召回数量、模型候选和阈值在对应任务中评估，不照搬 GoGo 参数。
