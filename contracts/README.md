# contracts/

跨模块协议契约目录。当前已定义账号认证 REST 与 shopping-mcp 模拟查询工具契约。

后续按下列约定存放，避免 Python、React、Java 各自维护一份不一致的接口定义：

| 目录（后续创建） | 内容 |
| --- | --- |
| `contracts/rest/` | Python REST 接口契约；当前见[账号认证与服务端会话](rest/auth.md) |
| `contracts/sse/` | 后台任务事件类型、字段与顺序 |
| `contracts/mcp/` | Python 客户端接入外部及模拟 MCP 服务的工具名、入参、返回结构与适配约定；当前见 [`search_products`](mcp/shopping-search-products.md) |
| `contracts/cards/` | 网页展示用的方案卡片结构 |

约定：

- 契约文件与实现同步修改；不要只改一端。
- 示例数据只用于说明字段，不代表已接入真实业务。
- 当前 REST 仅有公开健康检查与认证基础，没有私有业务资源、产品对话 SSE 或卡片协议。MCP 内部 Streamable HTTP 传输不等于产品对话 SSE。
