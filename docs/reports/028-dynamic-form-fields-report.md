# 028 扩展动态表单的场景字段报告

## 结论

028 已完成。本次扩展了受控动态表单的字段能力，同时保留 021 的 shopping 默认四字段、任务 revision、确认幂等、历史读取和预算复算语义。未新增数据库迁移：`TaskRevision.conditions` 与 `DynamicFormProposal.schema/confirmed_values` 已是 JSON 快照，新增字段在服务层完成 domain-aware 校验后复用既有原子 revision 写入。

## 实现

- 表单注册表按 domain 管理字段。shopping 模型 proposal 可提出 `color`、`use_case` 单选；travel 默认表单支持 `destination` 地点文本、`start_date`、`end_date` 日期和 `activity_types` 多选。
- 服务端校验控件、字段 ID、注册选项、单位、范围、重复字段、选项数量/长度、日期格式和日期先后；确认值拒绝未知字段、错误值类型、重复多选和 `<`/`>` 标记字符。模型 proposal 仍只保存为待确认提议，确认前不进入任务条件。
- `create_revision` 统一按任务 domain 调用 `validate_conditions`，新增 list[str] 条件并保持原有正数、长度、16 KiB、travel 日期顺序约束。
- 前端按 schema 渲染数字/金额、日期、单选、多选 checkbox 和地点/短文本，不使用 HTML 注入；API 条件类型同步扩展。
- coordinator 提示只公开受控字段 ID、控件和注册选项，不授权模型创建 URL、权限字段、工具或任意 UI 代码。

## 验证

### 替身与自动化证据

- `uv run ruff check src tests/test_tasks.py`：通过。
- `uv run pytest -q tests/test_tasks.py`：`9 passed`。
- `uv run pytest -q tests/test_tasks.py tests/test_runs.py`：`19 passed`。
- `uv run pytest -q`：`164 passed`。
- `npm run build`：通过。
- `npm run lint`：通过，保留仓库已有 3 条 React Hook warning，未新增阻断错误。

专项覆盖包括受控单选/多选 schema、脚本标记拒绝、旧购物四字段 proposal、条件合并、revision、幂等和 run 回归。自动化测试使用 TestClient/SQLite 替身，不代表真实外部服务 exactly-once。

### 本轮未执行的真实证据

本轮没有重新启动真实 DeepSeek、独立 Worker、PostgreSQL 或 Chrome，因此没有把真实模型为“选择通勤雨衣”和“规划城市周末活动”生成不同字段的结果写成已验收证据。027 已有的 Tavily 真实证据不等同于 028 新字段真实闭环。真实模型输出仍会经过服务端注册表和确认校验，失败时不会写入任务条件。

## 数据与安全决策

扩展字段属于 owner-scoped 普通任务业务数据；不接受密钥、服务 URL、权限标识或支付资料作为注册字段。proposal 与 revision 继续绑定任务和 revision，确认沿用 owner、当前 revision、唯一请求 ID、事务和并发冲突校验。外部模型只产生待确认 schema，不能直接修改条件；本任务没有外部写操作，也不宣称外部 exactly-once。

## 范围边界

地点字段是受控短文本，不是地图定位控件；本任务没有实现出行全流程、知识库、任意自定义字段或新的 MCP 工具。按任务要求完成 028 后停止，不执行 029。
