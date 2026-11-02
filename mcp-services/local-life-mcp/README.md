# local-life-mcp

本地生活与外卖 Java 服务骨架，默认端口 **8103**，Java 包 `dev.lifebuy.locallife`。

## 当前内容

- Spring Boot 启动类 `LocalLifeMcpApplication`
- Spring Web（`spring-boot-starter-webmvc`）与 Actuator
- 仅暴露 `GET /actuator/health`

## 后续用途（本轮未实现）

门店、菜单、规格和口味查询；MCP 协议层、工具注册与业务接口将在后续阶段接入。

## 运行

```bash
cd mcp-services
./mvnw -pl local-life-mcp spring-boot:run
curl http://127.0.0.1:8103/actuator/health
```
