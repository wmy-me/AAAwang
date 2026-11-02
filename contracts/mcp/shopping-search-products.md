# shopping-mcp `search_products` 契约

本契约只描述本项目 Java 模拟服务的示例工具，不是所有外部 MCP 商品工具必须遵守的统一 schema。数据全部来自内存固定样例，不代表真实平台价格、库存或商品身份。

## 工具

- 服务 ID：`shopping`
- 原始工具名：`search_products`
- 客户端限定身份：`shopping:search_products`
- 传输：MCP Streamable HTTP，默认 `http://127.0.0.1:8101/mcp`
- 行为：只读，不写入任何状态

## 输入

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| `keyword` | string | 是 | 去除首尾空白后非空，最长 50 个字符 |
| `max_price` | decimal | 否 | 非负单价上限，货币固定为 CNY |
| `limit` | integer | 否 | 默认 5，范围 1 至 10 |

## 成功输出

```json
{
  "products": [
    {
      "product_id": "mock-pencil-set",
      "name": "彩色铅笔套装",
      "unit_price": 12.80,
      "currency": "CNY",
      "unit": "12支/盒"
    }
  ],
  "source_type": "mock",
  "source_service": "shopping-mcp"
}
```

无匹配是正常成功结果：`products` 为空数组，`source_type` 和 `source_service` 仍保留。Python 通用客户端原样保留 MCP 内容块、结构化结果与 `isError`，不根据名称重建商品对象。

## 错误

空关键词、超过长度限制、负 `max_price`、小于 1 或大于 10 的 `limit` 是工具执行错误，通过 MCP 调用结果的 `isError=true` 表达，不伪装为空结果。未知工具、服务不可用、协议失败和超时由 Python 客户端分别报告。