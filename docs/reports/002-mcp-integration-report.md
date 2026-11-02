# 002 通用 MCP 客户端与 Java 模拟查询服务报告

**项目：** 生活采买智能体  
**阶段：** P1 最小 Agent 能力验证  
**执行日期：** 2026-11-02  
**任务代码基线：** `37634c7f6acf7fc9e7ba9d357032bc0509eface1`  
**实际执行起点：** `8459e407f890061045dcb53b03ef98168cc656c8`（后续仅有 002 文档）  
**结论：** 已完成。Python 官方 SDK 与独立 Java 服务通过标准 MCP Streamable HTTP 完成初始化、工具发现、调用和资源清理。

## 1. 版本与方案

| 部分 | 实际版本与选择 |
| --- | --- |
| Python | 官方 `mcp` 2.3.0，Python 3.12；URL 客户端使用 Streamable HTTP |
| Java | Spring AI 2.0.2 WebMVC MCP Server starter；该版本官方支持 Spring Boot 4.0/4.1 |
| Java MCP SDK | 2.1.0，由 Spring AI BOM 传递管理 |
| 运行时 | Spring Boot 4.1.2、JDK 21 |
| 协商结果 | MCP `2025-11-25` |

没有手写普通 JSON Controller。Spring AI 注册标准 `/mcp` 端点与工具 schema，Python SDK执行协议初始化、发现和调用。

## 2. 实现

- Python Settings 通过 `MCP_SERVICES` JSON按服务 ID配置 URL、传输、超时、启用状态和秘密类型认证预留；模块导入和 FastAPI 启动不连接服务。
- 通用客户端的工具身份为 `服务ID:原始工具名`，不硬编码商品结构；保留 SDK 的描述、schema、内容块、结构化结果和 `isError`。
- 连接、发现和调用均有超时，异步上下文负责释放会话。未知服务、禁用服务、未知工具、连接失败、超时、协议失败和工具执行失败使用不同异常类型。
- shopping-mcp 只注册 `search_products`，使用少量内存固定数据。返回 `product_id`、名称、十进制单价、CNY、单位、`source_type=mock` 和 `source_service=shopping-mcp`。
- 服务绑定 `127.0.0.1:8101`。Spring starter 默认未拒绝恶意 Origin，因此增加 `/mcp` Origin 过滤；最终远程 Origin 返回 403。
- 契约位于 `contracts/mcp/`。travel-mcp、local-life-mcp、网页、LLM 和 Agent 未改为工具调用链路。

## 3. 真实 MCP 联调

启动：

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
```

客户端检查：

```bash
cd backend
uv run python scripts/check_mcp.py --service shopping
```

实际结果：协议版本 `2025-11-25`；服务端 `shopping-mcp 0.1.0`；发现唯一工具 `search_products`；查询关键词“笔”、最高单价 15 CNY、limit 2，返回 2 个模拟候选，首项为“彩色铅笔套装”。输出 schema 与结构化结果均由服务端提供，模拟来源标记通过。

另外通过真实协议检查：无匹配返回成功且 `products=[]`；空关键词返回 `isError=true`。最终 `GET /actuator/health` 返回 200，恶意 Origin 的 initialize POST 返回 403。验证后已停止本轮启动的服务。

## 4. 自动检查

| 检查 | 结果 | 模式 |
| --- | --- | --- |
| `uv run pytest -q` | 13 passed（7 个既有 LLM、6 个 MCP） | 本地测试；MCP 部分使用受控 SDK 替身 |
| Python MCP 通用性 | shopping 与 alternate 两个服务 ID复用同一客户端并产生不同限定身份 | 受控替身，不替代真实联调 |
| Python 失败分支 | 未知服务、未知工具、工具错误结果保留、连接失败、初始化超时 | 受控替身 |
| 停服检查 | 脚本非零退出并报告初始化失败 | 真实本地停服；SDK 将底层连接拒绝封装为初始化失败 |
| `uv run ruff check src scripts tests` | 通过 | 本地静态检查 |
| `python -m compileall`、`uv lock --check` | 通过 | 本地编译与锁文件检查 |
| `./mvnw -B -ntp verify` | Reactor 4 模块全部成功；shopping 6 tests passed | 真实 Maven 多模块构建 |
| Origin | 无 Origin 和本地 Origin 测试通过；远程 Origin 测试与真实请求均为 403 | Java 单元测试与真实 HTTP |

## 5. 边界与后续

- 本轮未调用 LLM；001 的模型结果没有作为 MCP 证据，也没有重复真实模型请求。
- 认证参数仅预留，配置后会明确拒绝；OAuth 和外部服务认证尚未实现。
- 模拟结果不是公开平台事实，不代表价格或库存。
- 普通 MCP 初始化、发现和调用成功不代表 LLM 会正确选择工具。后续需另立 003 完成模型工具调用验证。