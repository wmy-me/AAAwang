# tools/

工具集成层目录。工具实现只负责协议适配和受控调用；Agent 能力、用户权限、预算和 Run 生命周期由上层服务端负责。

| 子目录 | 后续职责 |
| --- | --- |
| `mcp/` | 通用 Streamable HTTP MCP 客户端、初始化、工具发现、schema 和错误分类 |
| `maps/` | 地点搜索与天气适配器；只调用配置允许的地图 MCP 工具 |
| `search/` | 通用搜索与网页信息获取 |
| `knowledge/` | 知识库检索与证据引用 |

商品 Agent 通过 `run_tool_loop` 只暴露 `shopping:search_products`，地图和天气由 Worker 根据受信能力快照调用。模型不能提供 URL、服务 ID 或工具名来扩大范围；`modules/capabilities/routing.py` 先将静态能力与实时 MCP `list_tools` 结果取交集，执行前再次校验，`RunBudget` 统一约束模型、委派、MCP、远程调用和墙钟预算。

不要在工具层放置 Agent prompt、场景 Skill、业务金额计算或 Run 租约逻辑。模拟商品服务必须保留来源标记，不能把模拟库存或价格描述成真实电商事实。
