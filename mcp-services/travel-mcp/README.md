# travel-mcp

出行信息 Java 服务骨架，默认端口 **8102**，Java 包 `dev.lifebuy.travel`。

## 当前内容

- Spring Boot 启动类 `TravelMcpApplication`
- Spring Web（`spring-boot-starter-webmvc`）与 Actuator
- 仅暴露 `GET /actuator/health`

## 后续用途（本轮未实现）

交通与酒店查询；MCP 协议层、工具注册与业务接口将在后续阶段接入。

## 运行

```bash
cd mcp-services
./mvnw -pl travel-mcp spring-boot:run
curl http://127.0.0.1:8102/actuator/health
```
