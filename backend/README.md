# backend/ — Python 主后端

生活采买智能体的 Python 主系统，使用 **uv** 管理 Python 版本、虚拟环境、依赖和运行命令。

## 当前实现边界

- FastAPI 应用入口与唯一的 `GET /api/health` 健康检查接口。
- `pydantic-settings` 读取应用名称、运行环境与日志级别。
- 已安装 LangGraph 基础依赖，但未编写状态图、Agent、提示词或工具调用。
- `agents/`、`tools/`、`modules/`、`db/`、`worker/` 只有职责说明与预留目录。
- 启动不依赖数据库、模型凭据或三个 Java 服务。

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

本阶段尚无业务接口、数据库连接、MCP 客户端或后台 Worker。
