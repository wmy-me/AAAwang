# 027：公开网页搜索 MCP 与来源引用执行报告

## 结论

027 的受控公开网页搜索实现和真实验收已完成。真实 Tavily 协议、真实 DeepSeek 选择、独立 Worker 搜索 Run、PostgreSQL 持久化、Chrome 刷新重读和双用户隔离均已通过。Tavily key 只通过本次 API/Worker 进程环境提供，未写入仓库或报告。

## 已实现

- 新增 `web_search` 只读能力，服务 ID 为 `tavily`，工具白名单为 `tavily_search`。
- 新增 `TAVILY_MCP_URL`、`TAVILY_MCP_KEY`、`TAVILY_MCP_TIMEOUT_SECONDS`、`TAVILY_MCP_ENABLED` 和 `TAVILY_MCP_TOOL_NAME` 配置；key 使用 `SecretStr`，不进入响应、日志或模型提示。
- 新增受控搜索适配器：只发送 query 和有界 max_results，校验已发现工具 schema，过滤非 HTTP(S)、本地和内网地址，限制字段和结果数量，并分类鉴权、超时、限流、连接和协议错误。
- 搜索来源按 owner、task、revision、run 私有持久化，提供 `/runs/{run_id}/web-search` 读取接口；网页来源与商品候选、地图和天气结果分开展示。
- Worker 支持独立 `web_search` Run 以及与现有能力的受控组合，沿用预算、租约、取消和终态持久化边界。
- 添加 Tavily 配置示例与协调 Agent 选择规则；未启用或未发现兼容工具时能力不可见。

## 验证证据

- `uv run ruff check src scripts tests`：通过。
- `uv run python -m compileall -q src scripts tests`：通过。
- `uv run pytest -q`：`164 passed`。
- `uv run alembic upgrade head`：应用 `20261105_0018 -> 20261105_0019` 成功。
- `uv run alembic check`：无新升级操作；保留 SQLAlchemy 关于既有 `messages`/`runs` 表循环依赖的警告。
- `npm run lint`：通过，保留仓库既有 React Hook warnings。
- `npm run build`：通过。
- 搜索替身覆盖服务缺失、空/非法来源、公开 URL 规范化、schema 不兼容、鉴权和超时错误，以及 key 不出现在错误文本。

## 真实闭环证据

- 真实 MCP 直连：`tavily_enabled=True`，`tavily_service_configured=True`，实际使用 `tavily_search` 返回 10 条公开来源。
- 真实 Run：`dda09f3d-5792-4244-a112-b9468d969e13` 完成，`execution_type=web_search`，能力为 `web_search`；Run 决策来源为 `deepseek_structured_worker`，模型请求 1 次，MCP 尝试 1 次，来源快照持久化 10 条。
- 数据库刷新重读：同一会话重新读取 `/api/runs/{run_id}/web-search` 返回 10 条来源。
- Chrome 刷新：真实 Chrome page 中刷新前后 Run 与来源接口均为 HTTP 200，来源数量均为 10。
- 第二用户隔离：第二用户读取同一 Run 和 `/web-search` 均返回 HTTP 404。

以上替身测试与真实证据分开记录；真实 Tavily MCP、DeepSeek、Worker、PostgreSQL 和 Chrome 验收均已执行。

## 密钥与复现

本次验收使用进程环境提供的本地 key 启动 API 和 Worker，并设置 `TAVILY_MCP_ENABLED=true`；项目未改写 key，也未在报告、日志或聊天中记录 key。当前 Settings 默认只读取仓库根目录 `.env`（进程环境变量可覆盖），不会自动读取 `backend/.env`；后续复现应在根目录 `.env` 或等价进程环境中配置。外部只读搜索可重试，不承诺 exactly-once。

## 数据与幂等边界

搜索结果属于用户私有的外部资料快照，不保存整页正文，不作为商品报价、库存或订单事实。读取按 owner 和 Run 绑定校验；同一 Run 的结果使用 URL 派生键避免终态重复写入。外部搜索调用状态不确定时不宣称 exactly-once，Worker 仍以租约 fencing 和终态事务保护本地写入。
