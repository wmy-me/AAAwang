# mcp-services/ — 三个 Java 服务骨架

Maven 多模块工程，父工程统一管理 Spring Boot 与 Spring AI 版本。`shopping-mcp` 已接入标准 MCP；另外两个模块仍为健康检查骨架。

| 模块 | Java 包 | 端口 | 后续职责（本轮未实现） |
| --- | --- | --- | --- |
| `shopping-mcp` | `dev.lifebuy.shopping` | 8101 | Streamable HTTP MCP 与一个只读模拟商品查询工具 |
| `travel-mcp` | `dev.lifebuy.travel` | 8102 | 交通与酒店查询 |
| `local-life-mcp` | `dev.lifebuy.locallife` | 8103 | 门店、菜单、规格和口味查询 |

## 定位

这些工程用于模拟成熟的外部 MCP 服务，验证 Python 侧统一客户端的接入与工具调用。三个领域是测试与演示场景，后续可扩展其他 MCP 服务。当前只有 shopping-mcp 实现协议与少量固定模拟数据，不是商城后台。详见 [项目定位](../docs/overview/project.md)。

## 技术版本

- Spring Boot 4.1.2（正式版，三个模块统一锁定）
- Spring AI 2.0.2（BOM 管理；支持 Spring Boot 4.0/4.1）
- MCP Java SDK 2.1.0（由 Spring AI 传递管理）
- Web starter：`spring-boot-starter-webmvc`（Spring Boot 4 中替代 `spring-boot-starter-web`）
- JDK 21
- Maven Wrapper（无需全局 Maven）

## 构建与检查

```bash
cd mcp-services
./mvnw -B -ntp verify
```

构建产物为各模块 `target/*.jar`，不提交。shopping-mcp 包含查询边界与 Origin 过滤测试。

## 启动

```bash
cd mcp-services
./mvnw -pl shopping-mcp spring-boot:run
./mvnw -pl travel-mcp spring-boot:run
./mvnw -pl local-life-mcp spring-boot:run
```

分别访问：

- <http://127.0.0.1:8101/actuator/health>
- <http://127.0.0.1:8102/actuator/health>
- <http://127.0.0.1:8103/actuator/health>

shopping-mcp 另外暴露回环地址上的 `/mcp`，使用 Streamable HTTP，只注册 `search_products`；无 Origin 的后端 SDK 请求允许，浏览器 Origin 仅允许 localhost/127.0.0.1。travel 与 local-life 仍只暴露健康端点。
