# shopping-mcp

购物采买 Java 模拟 MCP 服务，默认绑定 `127.0.0.1:8101`，Java 包 `dev.lifebuy.shopping`。

## 当前内容

- Spring Boot 启动类 `ShoppingMcpApplication`
- Spring AI 2.0.2 WebMVC MCP Server，Streamable HTTP 端点 `/mcp`
- 一个只读工具 `search_products`，只查询固定内存模拟数据
- `GET /actuator/health` 健康检查
- MCP Origin 过滤：无 Origin 的后端请求及本地 Origin 可用，其他 Origin 返回 403

输入输出及错误约定见 [`contracts/mcp/shopping-search-products.md`](../../contracts/mcp/shopping-search-products.md)。模拟价格和商品不代表真实平台信息；服务无数据库、写入工具、模型或商城后台。

## 运行

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
curl http://127.0.0.1:8101/actuator/health
```

另一个终端从 Python 官方 SDK 验证协议：

```bash
cd backend
uv run python scripts/check_mcp.py --service shopping
```
