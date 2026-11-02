# contracts/

跨模块协议契约的预留目录。本轮不定义任何具体协议或接口文件。

后续按下列约定存放，避免 Python、React、Java 各自维护一份不一致的接口定义：

| 目录（后续创建） | 内容 |
| --- | --- |
| `contracts/rest/` | Python REST 接口的 OpenAPI 文档或手写契约 |
| `contracts/sse/` | 后台任务事件类型、字段与顺序 |
| `contracts/mcp/` | Python 客户端接入外部及模拟 MCP 服务的工具名、入参、返回结构与适配约定 |
| `contracts/cards/` | 网页展示用的方案卡片结构 |

约定：

- 契约文件与实现同步修改；不要只改一端。
- 示例数据只用于说明字段，不代表已接入真实业务。
- 本轮没有 REST 业务接口、SSE、MCP 工具或卡片协议。
