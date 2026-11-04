# 021：自然语言任务与动态表单执行报告

- 状态：部分实现
- 任务文档：[021](../vibe%20coding/021-dynamic-task-forms.md)
- 设计依据：[动态表单设计](../design/dynamic-task-forms.md)
- 数据与幂等依据：[数据保护与幂等设计规则](../design/security-and-idempotency.md)

## 已实现

- 新增 `dynamic_form_proposals` 表，按 `task_id + task_revision_id` 保存受限表单提议；同任务的 `client_request_id` 唯一。
- 服务端只生成 shopping 注册字段：`item`、`people`、`quantity`、`budget`，包含控件、标签、原因、单位和范围；模型不能提交 HTML、脚本、工具权限或身份字段。
- `GET /api/tasks/{task_id}/form` 返回当前 task revision 的提议；提议状态和确认值独立于任务条件。
- `POST /api/tasks/{task_id}/form/submit` 校验 proposal、字段白名单、类型、范围、任务归属和 expected revision；确认值在同一事务中创建新的 `TaskRevision`、用户 `Message` 和 `capability_decision` `Run`，返回三者及最新任务。
- 相同请求 ID 和相同值返回同一 revision；相同请求 ID 携带不同值被拒绝。过期 revision、未知字段、非法值和跨账号访问被拒绝。
- 网页在任务卡下展示待确认字段，支持短文本、数字和金额输入；确认后刷新任务和当前表单。切换任务或提议变化时重置未提交输入，空字段集不展示。自然语言聊天入口仍可继续使用，表单不是每轮必经步骤。

## 验证

- 动态表单与 capability Worker 专项：`20 passed`。
- 后端全量回归：`128 passed`。
- Ruff、compileall、Alembic 迁移升级与前端 TypeScript build 通过。
- 前端 lint 通过，保留 3 条 React Hook warnings（含本次新增 `set-state-in-effect`）。
- 本地数据库已从 `20261104_0016` 升级到 `20261104_0017`。

### 真实联调（2026-11-04）

- **真实 DeepSeek schema**：Worker 决策 Run `607a605a-ff30-4e85-a393-0360fba5dae5` 返回 `people/quantity/budget` 三项；任务 `5d3a31e3-4a8c-4c15-8992-6a2be44f92a2` 的 `GET /form` 重读为 `source=deepseek_structured_worker`，字段与会话校验后的持久化 schema 一致。联调中发现 128 completion tokens 会截断多字段 JSON，已将决策调用提升到 512 tokens，并在提示中写明受限字段结构。
- **表单提交与 Worker**：任务 `17bda4b6-fc4e-489c-9326-587952ff8723` 的模型提议 `0570c2ae-fab5-42e5-8ab3-b54979b9560a` 确认后创建消息 `e68e8e0b-e7e7-4270-af5d-bd6b318804b2`、`capability_decision` Run `4ea997ee-4e23-460d-a851-1320d427db93` 和任务 REV3；Run 由独立 Worker 消费为 `completed`（本次模型判断为 `direct_answer`），预算 `model_requests=2`、`remote_calls=2`。相同请求 ID/值重试复用同一消息与 Run；旧 revision 返回 409，第二账号返回 404。
- **真实浏览器**：使用本机 Chromium（Playwright 无头）登录账号 `cap021w8c3632`，任务 `32302b69-b049-4e4e-abde-f2453b3ca2d4` 显示 REV2 和模型提议的 `quantity/people/budget` 字段；填写 25/25/200 并提交后提示进入 REV3，Run `849b1f0d-c195-46e6-bbe4-e9e7e30dcb8b` 在网页内完成；刷新后条件仍为 `预算 ¥200 / 25 人 / 25 件`，REV 仍为 3，无错误提示。浏览器截图仅保存在 `/tmp`，未提交仓库。

## 尚未验收

- 多目标追问、目标变更后重新生成字段，以及“无预算探索”之外的动态字段组合尚未专项验收。
- 表单确认创建的 `capability_decision` Run 本轮被模型判为 `direct_answer`，不会自动执行商品能力；表单确认是否应自动触发一次采购 Run 仍属产品语义，未实现也未验收。
- 当前首版只实现 shopping 字段，travel 和多选/日期/地点控件保留在契约类型中但未开放。
- 浏览器验收为 Playwright 无头 Chromium，未执行有头浏览器人工交互；同一任务并发重复提交只做了顺序幂等验证。
- 真实模型 schema 输出存在非确定性，联调中偶发返回未注册 `kind` 被服务端拒绝；这会被记录为失败 Run，不产生表单写入。

## 数据保护与幂等决策

表单 schema、确认值和普通任务条件属于当前用户任务范围内的普通业务数据，按 owner/task/revision 查询，不进入日志或模型外部上下文。表单确认是有副作用的 revision 创建，使用任务当前 revision 做乐观并发，使用 `task_id + client_request_id` 做唯一幂等作用域；重复相同请求复用原 revision，不同值冲突。当前没有外部写入，不宣称跨系统 exactly-once。
