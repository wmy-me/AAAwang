# backend/ — Python 主后端

生活采买智能体的 Python 主系统，使用 **uv** 管理 Python 版本、虚拟环境、依赖和运行命令。

## 当前实现边界

- FastAPI 应用入口与唯一的 `GET /api/health` 健康检查接口。
- `pydantic-settings` 读取应用名称、运行环境与日志级别。
- DeepSeek 普通文本适配器、一次调用上限的 MCP 工具循环与本地检查脚本；不提供 HTTP 聊天接口。
- 官方 MCP Python SDK 的通用服务配置、工具发现与调用入口，以及本地检查脚本。
- 已安装 LangGraph 基础依赖，但未编写状态图或 Agent；工具循环是独立的有限执行器。
- API 启动不依赖数据库、模型凭据或 Java 服务；检查脚本才按需连接外部服务。

## 环境与安装

```bash
cd backend
uv sync --locked
```

Python 版本由 `.python-version` 固定为 3.12，依赖锁定在 `uv.lock`，虚拟环境位于 `backend/.venv/`（不提交）。

## 启动

```bash
cd backend
uv run uvicorn life_agent.main:app --host 127.0.0.1 --port 8000
```

- 健康检查：<http://127.0.0.1:8000/api/health>
- 接口文档：<http://127.0.0.1:8000/docs>

## 检查

```bash
cd backend
uv run ruff check src
uv run python -m compileall -q src
uv run pytest -q
```

## 配置

复制模板并按需修改（模板不包含任何真实密钥）：

```bash
cp .env.example .env
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `life-buy-agent-api` | 应用名称，也用于健康检查返回 |
| `APP_ENV` | `development` | 运行环境标识 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LLM_PROVIDER` | `deepseek` | 本轮唯一支持的供应商 |
| `LLM_MODEL` | `deepseek-flash` | DeepSeek 官方模型 ID |
| `LLM_BASE_URL` | `https://api.deepseek.com` | DeepSeek OpenAI 格式 API 地址 |
| `LLM_API_KEY` | 无 | 模型检查必需；只写入本地 `.env` |
| `LLM_TIMEOUT_SECONDS` | `60` | 单次请求超时秒数 |
| `MCP_SERVICES` | shopping 本地映射 | 按服务 ID 配置 URL、传输、超时、启用状态和可选认证 token 的 JSON 对象 |

配置有效密钥后执行一次真实请求：

```bash
cd backend
uv run python scripts/check_llm.py
```

脚本禁用 SDK 自动重试，成功时输出供应商、模型、耗时、最多 200 个字符的回复，以及服务实际返回时的 token 用量。失败时返回非零退出码，不输出密钥、认证头或供应商异常正文。

启动 `shopping-mcp` 后执行真实 MCP 检查：

```bash
cd backend
uv run python scripts/check_mcp.py --service shopping
```

脚本使用配置中的服务 ID完成初始化、工具发现和一次 `search_products` 调用。MCP 客户端不硬编码商品结构；脚本只针对本轮示例验证 `source_type=mock`。认证字段已用秘密类型预留，但本轮本地服务无认证，配置认证 token 时会明确拒绝而不会误发。

同时配置密钥并启动 `shopping-mcp` 后，可验证真实模型工具闭环：

```bash
cd backend
uv run python scripts/check_tool_loop.py --service shopping \
	--prompt "我想买一盒彩色铅笔，单价不超过15元。请查询模拟商品后回答。"
```

执行器只向模型暴露允许的已发现工具，校验参数 schema，最多执行一次 MCP 调用和一次后续模型回复。检查脚本要求真实 tool_call，并核对模拟来源、实际候选名与价格；直接回答不记为闭环成功。

本阶段尚无聊天 API、数据库连接、Agent 图或后台 Worker。
