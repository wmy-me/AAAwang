# 028 扩展动态表单的场景字段报告

## 结论

028 部分完成：动态字段已有实现和一个真实模型/Worker/数据库场景；网页实际填写提交、第二个真实场景及动态字段经 revision 接口写入的校验边界尚待补证。此前 `8bebb53` 的版本仍把字段限制在预设注册表；本轮已改为“模型生成业务字段、服务端校验受控 schema、用户确认后写入 revision”，并记录真实模型/Worker/PostgreSQL 场景及 Chrome 打开、刷新和接口读取。同时保留 021 的 shopping 默认四字段、任务 revision、确认幂等、历史读取和预算复算语义。未新增数据库迁移：`TaskRevision.conditions` 与 `DynamicFormProposal.schema/confirmed_values` 已是 JSON 快照。

## 实现

- 核心 `item/people/quantity/budget` 继续使用确定性控件、单位和数值边界；模型可生成未预设的业务字段，例如真实任务中的 `fabric`、`waterproof_level`、`hat_type`、`season`，也可为 `color` 生成当前场景选项。
- 服务端允许最多 8 个字段、字段 ID 为 1–32 位 snake_case、最多 12 个选项、选项长度最多 80、schema 文本无 HTML/脚本/控制字符；选择控件必须有 2–12 个互不重复选项，数字控件范围限制在 0–100000000 且 min 不大于 max。身份、权限、凭据、服务 URL、工具和支付相关字段名保留拒绝。
- 确认值拒绝未知字段、错误值类型、重复多选和 `<`/`>` 标记字符；模型 proposal 仍只保存为待确认提议，确认前不进入任务条件。`create_revision` 统一按任务 domain 校验动态条件，保留原有正数、长度、16 KiB、travel 日期顺序约束。
- 前端按 schema 渲染数字/金额、日期、单选、多选 checkbox 和地点/短文本，不使用 HTML 注入；API 条件类型同步扩展。
- coordinator 根据当前目标决定直答、追问、工具或表单；表单提示只约束业务名、受支持控件、资源上限和安全边界，不再列举固定业务字段或固定选项。

## 验证

### 替身与自动化证据

- `uv run ruff check src tests/test_tasks.py`：通过。
- `uv run pytest -q tests/test_tasks.py tests/test_runs.py`：`21 passed`。
- `uv run pytest -q`：`166 passed`。
- `uv run alembic check`：通过，数据库版本 `20261105_0019`，无新增迁移。
- `npm run build`：通过。
- `npm run lint`：通过，保留仓库已有 3 条 React Hook warning，未新增阻断错误。

专项覆盖包括受控单选/多选 schema、脚本标记拒绝、旧购物四字段 proposal、条件合并、revision、幂等和 run 回归。自动化测试使用 TestClient/SQLite 替身，不代表真实外部服务 exactly-once。

### 真实闭环证据

- 真实环境：DeepSeek、独立 Worker、PostgreSQL（Compose，宿主端口 55432）、shopping-mcp（8101）和 Vite 前端均已运行；迁移检查无差异。
- 真实模型首次返回核心字段时验证了旧字段兼容；随后明确要求通勤雨衣偏好，DeepSeek 生成并由 Worker 持久化了 5 个非预设字段：`color`、`fabric`、`waterproof_level`、`hat_type`、`season`，每项包含模型生成的不同选项。
- 真实提交选择：`color=黑色`、`fabric=尼龙`、`waterproof_level=高防水`、`hat_type=连帽`、`season=四季通用`。任务从 revision 1 进入 revision 2，条件快照只包含这些确认值；proposal 状态为 `confirmed`，消息与 Run 均关联同一 revision。
- 后续真实 Run 使用 revision 2 条件，DeepSeek 选择 `shopping_product_discovery`，Worker 调用 shopping MCP；返回无匹配候选时明确标记模拟来源并不补造价格/库存，Run 最终 `completed`。
- Chrome CDP 使用真实登录 session 打开前端并刷新；刷新后同源 API 读取到 `revision=2` 及上述五个条件，页面 title 为“生活采买智能体”、React root 正常存在。
- 真实测试中发现旧的 `color` 固定选项校验会丢弃整个动态 proposal，已移除该固定选项阻断；修复后重新启动 Worker、重新运行 DeepSeek、提交、Run 和 Chrome 刷新，全部通过。远端 `git pull --ff-only` 两次因 GitHub TLS 握手失败，当前 HEAD 为 `8bebb53`，未能取得更远端提交。

## 数据与安全决策

扩展字段属于 owner-scoped 普通任务业务数据；不接受密钥、服务 URL、权限标识或支付资料作为注册字段。proposal 与 revision 继续绑定任务和 revision，确认沿用 owner、当前 revision、唯一请求 ID、事务和并发冲突校验。外部模型只产生待确认 schema，不能直接修改条件；本任务没有外部写操作，也不宣称外部 exactly-once。

## 范围边界

地点字段是受控短文本，不是地图定位控件；本任务没有实现出行全流程、知识库、任意自定义字段或新的 MCP 工具。按任务要求完成 028 后停止，不执行 029。
