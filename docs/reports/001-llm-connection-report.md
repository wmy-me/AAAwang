# 001 真实模型接入与最小调用验证报告

**项目：** 生活采买智能体  
**阶段：** P1 最小 Agent 能力验证  
**执行日期：** 2026-11-02  
**起始提交：** `5d6198de602cdd10b5f295e65b1c8288ba948f45`  
**结论：** 已完成。实现、本地受控替身检查与一次真实 DeepSeek 普通文本请求均通过。

## 1. 实现

- 供应商为 DeepSeek，模型为 `deepseek-flash`，官方 OpenAI 格式 Base URL 为 `https://api.deepseek.com`。
- 使用 `openai` Python SDK 的异步客户端，原因是 DeepSeek 官方文档明确支持该格式，且 SDK 提供超时、连接与 HTTP 状态异常分类。本实现设置 `max_retries=0` 和 60 秒超时。
- 沿用现有 `Settings`，密钥使用 `SecretStr`。FastAPI 导入和健康检查不校验密钥、不创建客户端、不发远程请求。
- `scripts/check_llm.py` 发送一次固定普通文本请求，只输出供应商、模型、状态、耗时、最多 200 个字符的回复和供应商实际返回的 token 用量。
- 将认证失败、模型不存在、超时、连接失败、异常 HTTP 状态和空响应转换为不包含密钥或供应商异常正文的定位信息。

本轮没有新增 API、网页、LangGraph 图、MCP、Worker、会话或数据库能力。

## 2. 实际检查

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 依赖锁 | 通过 | `uv add openai`、`uv add --dev pytest` 后，`uv lock --check` 成功解析 59 个包 |
| 聚焦测试 | 通过 | `uv run pytest -q tests/test_llm.py` → `7 passed`；使用本地替身覆盖非空响应、空响应、认证失败、模型不存在、超时和客户端初始化失败，不是远程调用 |
| 缺配置 | 通过 | 无 `.env` 执行 `uv run python scripts/check_llm.py`，明确输出缺少 `LLM_API_KEY` 并返回退出码 1，未发请求 |
| 默认启动兼容 | 通过 | 无模型配置执行 `uv run python -c "from life_agent.main import app; print(app.title)"` → `life-buy-agent-api` |
| Ruff | 通过 | `uv run ruff check src scripts tests` → `All checks passed!` |
| Python 编译 | 通过 | `uv run python -m compileall -q src scripts tests` → 成功，无输出 |
| 编辑器诊断 | 通过 | 新增及修改 Python 文件无诊断 |
| 真实 DeepSeek 请求 | **通过** | `uv run python scripts/check_llm.py` → `deepseek-flash` 成功；耗时 0.93 秒；回复“已收到测试请求。”；服务报告输入 15、输出 5、合计 20 tokens |

首次真实检查在发出网络请求前发现当前机器使用 SOCKS 代理，而 SDK 的可选传输依赖未安装，客户端构造报错。通过 uv 添加 `socksio`，并将客户端初始化失败纳入安全错误映射后，聚焦测试与一次真实复测通过。没有循环发送请求。

## 3. 秘密保护

- `.env.example` 只包含空的 `LLM_API_KEY`，实际 `.env` 已由仓库根 `.gitignore` 忽略。
- 代码、测试、命令输出和本报告均无真实密钥、认证头或完整供应商错误正文。
- 未故意向真实服务发送错误凭据；失败分支由本地受控替身验证。

## 4. 完成范围

本机密钥只保存在被忽略的 `backend/.env`。后续需要复查普通文本连通时，在 `backend/` 执行：

```bash
uv run python scripts/check_llm.py
```

本任务的普通文本连通目标已完成。该结果不代表工具调用、结构化输出、流式响应、MCP 或完整 Agent 已验证。