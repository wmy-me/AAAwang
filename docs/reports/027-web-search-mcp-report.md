# 027：公开网页搜索 MCP 与来源引用执行报告

## 结论

027 的受控公开网页搜索实现已完成，后端、前端、迁移和测试替身验证通过；真实 Tavily 协议、真实 DeepSeek 选择、独立 Worker 搜索 Run 和浏览器验收暂受本地缺少 `TAVILY_MCP_KEY` 阻塞。密钥不通过聊天提供，待用户在本地环境补齐后再做真实验收。

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

以上测试使用受控替身，不代表已连接 Tavily。当前没有执行真实 `initialize/list_tools/call_tool`、真实 DeepSeek 选择、真实 Worker 搜索 Run 或浏览器搜索流程。

## 待补真实验收

用户后续说明已在本地 `backend/.env` 配置网页搜索 API；尚未验证其变量名及有效性。更正配置说明：当前 Settings 默认只读取仓库根目录 `.env`（进程环境变量可覆盖），不会自动读取 `backend/.env`。按 027 任务的配置核对步骤安全处理，在实际生效的配置中设置 `TAVILY_MCP_KEY` 并将 `TAVILY_MCP_ENABLED=true` 后，执行 Tavily 官方 MCP 的握手、工具发现和一次搜索；随后用真实 DeepSeek、独立 Worker、PostgreSQL 和浏览器验证来源展示、同一 Run 刷新重读及第二用户隔离。不得在报告、日志或聊天中记录 key。

## 数据与幂等边界

搜索结果属于用户私有的外部资料快照，不保存整页正文，不作为商品报价、库存或订单事实。读取按 owner 和 Run 绑定校验；同一 Run 的结果使用 URL 派生键避免终态重复写入。外部搜索调用状态不确定时不宣称 exactly-once，Worker 仍以租约 fencing 和终态事务保护本地写入。
