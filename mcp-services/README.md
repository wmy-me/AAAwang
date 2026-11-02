# mcp-services/ — 三个 Java 服务骨架

Maven 多模块工程，父工程统一管理 Spring Boot 版本。本轮只提供应用启动与 Actuator 健康检查，**尚未接入 MCP 协议、工具注册或任何业务查询**。

| 模块 | Java 包 | 端口 | 后续职责（本轮未实现） |
| --- | --- | --- | --- |
| `shopping-mcp` | `dev.lifebuy.shopping` | 8101 | 商城、二手商品及店铺查询 |
| `travel-mcp` | `dev.lifebuy.travel` | 8102 | 交通与酒店查询 |
| `local-life-mcp` | `dev.lifebuy.locallife` | 8103 | 门店、菜单、规格和口味查询 |

## 技术版本

- Spring Boot 4.1.2（正式版，三个模块统一锁定）
- Web starter：`spring-boot-starter-webmvc`（Spring Boot 4 中替代 `spring-boot-starter-web`）
- JDK 21
- Maven Wrapper（无需全局 Maven）

## 构建与检查

```bash
cd mcp-services
./mvnw -B -ntp verify
```

构建产物为各模块 `target/*.jar`，不提交。本轮没有业务测试，“构建成功”不代表业务测试通过。

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

服务只暴露 Actuator 的 `health` 端点，不输出健康详情。应用不连接数据库、不加载模型、不访问其他服务，也未创建 `/mcp` 路由。
