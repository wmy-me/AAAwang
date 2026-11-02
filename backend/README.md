# backend/ — Python 主后端

生活采买智能体的 Python 主系统，使用 **uv** 管理 Python 版本、虚拟环境、依赖和运行命令。

## 当前实现边界

- FastAPI 应用入口与唯一的 `GET /api/health` 健康检查接口。
- `pydantic-settings` 读取应用名称、运行环境与日志级别。
- DeepSeek 普通文本最小调用适配器与本地连通检查脚本；不提供 HTTP 聊天接口。
- 已安装 LangGraph 基础依赖，但未编写状态图、Agent、提示词或工具调用。
- `agents/`、`tools/`、`modules/`、`db/`、`worker/` 只有职责说明与预留目录。
- API 启动不依赖数据库、模型凭据或三个 Java 服务；只有模型检查脚本要求凭据。

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

配置有效密钥后执行一次真实请求：

```bash
cd backend
uv run python scripts/check_llm.py
```

脚本禁用 SDK 自动重试，成功时输出供应商、模型、耗时、最多 200 个字符的回复，以及服务实际返回时的 token 用量。失败时返回非零退出码，不输出密钥、认证头或供应商异常正文。

本阶段尚无聊天 API、数据库连接、MCP 客户端、Agent 图或后台 Worker。
