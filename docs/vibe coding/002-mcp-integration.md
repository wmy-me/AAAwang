# 002：通用 MCP 客户端与 Java 模拟查询服务

- 状态：待执行
- 所属阶段：P1 最小 Agent 能力验证
- 起始代码提交：`37634c7f6acf7fc9e7ba9d357032bc0509eface1`（执行前核对最新分支）
- 前置：000 工程骨架；001 普通文本模型接入已提交，验收见其报告
- 对应报告：`docs/reports/002-mcp-integration-report.md`
- 目标：Python 通过真实 MCP 协议连接 shopping-mcp，完成初始化、工具发现和一次只读查询
- 本轮不调用 LLM，不开发完整 Agent

## 1. 先读与现状

读取根 CLAUDE.md、[任务规则](README.md)、[项目定位](../overview/project.md)、[进度](../progress.md)、[路线图](../roadmap.md)，然后检查：

- `backend/src/life_agent/core/config.py`、`tools/mcp/`、`pyproject.toml`
- `mcp-services/pom.xml`、`shopping-mcp/pom.xml` 和启动配置
- `contracts/README.md`、`docs/guides/development.md`

当前 Java 只有 Spring Boot 4.1.2 / JDK 21 骨架，没有 MCP；Python 只有模型文本调用。保留 001 实现，不把模型文本连通当成工具调用证据。

## 2. 定位与范围

Java 提供模拟外部成熟 MCP 服务的查询能力。Python 使用通用客户端接入，后续增加其他 MCP 服务应主要增加配置和必要的领域适配，而不是复制客户端。

本轮只改 shopping-mcp；travel-mcp 和 local-life-mcp 保留骨架。模拟数据仅用于查询验证，标明模拟来源。不要求建设商城后台或数据库。

允许新增通用 MCP 客户端、服务配置、本地检查脚本、一个 Java 查询工具、相关契约和检查。Agent、网页聊天、会话持久化、SSE 对话、Worker、登录和订单不在本轮范围。MCP 传输内部可能使用 SSE，不等于开发产品对话 SSE。

## 3. SDK 与协议先验证

- Python 优先使用官方 MCP SDK；Java 优先评估 Spring AI 的 MCP Server WebMVC starter。
- 本轮采用 Streamable HTTP，示例服务地址 `http://127.0.0.1:8101/mcp`；以所选 SDK 的实际端点为准并写入配置。
- 执行时核对正式版 SDK、Spring Boot 4.1.2 与 JDK 21 的兼容矩阵和官方示例，记录最终版本及协议协商结果。不要仅复制旧版 SSE 配置。
- 若 starter 与现有版本不兼容，优先评估官方 Java MCP SDK 的最小适配，说明取舍；不要为一次接入擅自升级或降级所有模块。
- 安装并锁定实际使用的依赖，Python 使用 uv，Java 使用 Maven。先完成最小握手，再扩展工具。
- 不手写一个返回固定 JSON 的普通 Controller 冒充 MCP；使用标准的初始化、工具发现和调用流程。

## 4. Java 模拟查询工具

只注册一个只读工具，建议名 `search_products`：

| 输入 | 规则 |
| --- | --- |
| `keyword` | 必填非空关键词，限制长度 |
| `max_price` | 可选的非负单价上限，明确金额格式和货币 |
| `limit` | 有合理默认值和较小上限，由服务端限制 |

用少量内存固定数据查询，无匹配正常返回空集合；负价格、空关键词、越界 limit 等明确失败，不能伪装成成功。

结果包括模拟商品 ID、名称、单价、货币、规格或单位、模拟来源标记，例如 `source_type=mock`。候选数据应有来源服务标识；不要把模拟价格、库存当成真实平台信息。金额使用明确的十进制表示，Python 不根据名称重新猜测商品身份。

工具需有名称、描述和可发现的输入 schema；工具输出通过所选 SDK 合法编码，涉及工具执行错误时按协议及 SDK 表达。只读声明和服务器实际行为一致，不注册写入工具。

在 `contracts/mcp/` 保存该模拟工具的输入输出约定及示例，说明空结果与错误的区别。该领域输出约定不能被当成所有外部 MCP 工具的统一强制 schema。

## 5. Python 通用接入层

在已有 `tools/mcp/` 内实现，避免创建第二套工具集成目录。

- 按服务 ID 配置 URL、传输类型、超时、启用状态；默认不自动连接任何服务。
- 入口支持按服务 ID 连接、列出工具并保留其描述与 schema，以及调用指定工具和参数。
- 客户端不硬编码 search_products、Java 类型或商品结构；本地检查脚本可以知道本轮示例工具名。
- 工具身份包含服务 ID 与原始工具名，避免未来不同服务器的同名工具冲突。
- 不假定所有结果都是商品 JSON；保留 SDK 的内容块、结构化结果（若提供）和工具错误标志，再按需做领域适配。
- 会话、传输与客户端的生命周期处于正确的异步上下文；无论成功、异常或取消，均释放自己拥有的资源。
- 初始化、发现和调用都有明确超时。服务不可用、工具不存在、非法参数、协议错误、工具执行失败与正常空结果分别反馈。
- 不在 Settings 读取、模块导入或 FastAPI 启动时发起远程连接，保持 API 可独立启动。
- 配置由受信后端读取，CLI 以服务 ID 选择配置；不新增供任意网页用户提交地址的连接接口。
- 本地仅绑定回环地址，按所选 MCP 实现要求处理 Origin；未来外部服务的认证参数预留配置入口，秘密值不输出。本轮不实现 OAuth 或独立用户登录。

## 6. 本地检查入口与验证

建议提供 `backend/scripts/check_mcp.py`。在 backend 目录执行类似：

```bash
uv run python scripts/check_mcp.py --service shopping
```

先单独启动 shopping-mcp。脚本使用真实 SDK 完成初始化、工具发现、从发现结果确认示例工具、调用一次查询、验证模拟标记，然后关闭连接。输出服务 ID、协商结果、工具摘要和安全的查询摘要；失败返回非零退出码。

验证项：

| 检查 | 证据要求 |
| --- | --- |
| Java 构建 | 对受影响模块及必要父工程执行构建，记录实际命令 |
| 真实 MCP 联调 | 独立运行的 Java 服务与 Python SDK 完成握手、发现、调用、清理；记录实际版本和结果 |
| 查询行为 | 合法关键词得到候选；无匹配为空；非法参数明确失败 |
| 调用失败 | 服务不可用、未知工具和超时有明确结果；可用受控替身验证部分失败分支 |
| 通用性 | 通过配置或独立测试服务验证另一服务 ID 也使用同一客户端路径，不为它复制商品客户端 |
| 原能力兼容 | API 无模型密钥、Java 未启动时仍可启动；001 聚焦测试继续通过 |
| 秘密与来源 | 无密钥泄漏，模拟结果明确标注，未注册写入工具 |

替身检查不能替代 Python 到 Java 的真实 MCP 联调。测试环境没有 JDK 或无法下载依赖时报告阻塞，不能改成普通 HTTP 调用后标记成功。无须重复调用真实模型。

## 7. 完成后的文件

- 提交相关实现、实际依赖依据、示例配置和模拟工具契约。
- 更新 backend 与 shopping-mcp 的运行说明及开发指南。
- 创建对应报告：实际 SDK/协议版本、运行命令、真实联调与替身检查的区分、失败和未验证项。
- 更新进度与任务索引；验收缺口未解决时注明部分完成或受阻。
- 完成后停止。003 再验证 LLM 根据工具 schema 发出调用、执行工具并根据结果回答；不自动实现。

用户登录与资源隔离安排在 P2 的会话、任务和个人数据持久化之前，验收包含两个用户无法互相读取、修改或取消私有资源。本轮只查询共享模拟目录，不改变这一安排。

## 官方参考

- [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Spring AI MCP Server](https://docs.spring.io/spring-ai/reference/api/mcp/mcp-server-boot-starter-docs.html)

以上为资料入口，具体依赖与协商版本在执行时确认。
