# 021：自然语言任务与动态表单执行报告

- 状态：部分实现
- 任务文档：[021](../vibe%20coding/021-dynamic-task-forms.md)
- 设计依据：[动态表单设计](../design/dynamic-task-forms.md)
- 数据与幂等依据：[数据保护与幂等设计规则](../design/security-and-idempotency.md)

## 已实现

- 新增 `dynamic_form_proposals` 表，按 `task_id + task_revision_id` 保存受限表单提议；同任务的 `client_request_id` 唯一。
- 服务端只生成 shopping 注册字段：`item`、`people`、`quantity`、`budget`，包含控件、标签、原因、单位和范围；模型不能提交 HTML、脚本、工具权限或身份字段。
- `GET /api/tasks/{task_id}/form` 返回当前 task revision 的提议；提议状态和确认值独立于任务条件。
- `POST /api/tasks/{task_id}/form/submit` 校验 proposal、字段白名单、类型、范围、任务归属和 expected revision；确认值在同一事务中创建新的 `TaskRevision`。
- 相同请求 ID 和相同值返回同一 revision；相同请求 ID 携带不同值被拒绝。过期 revision、未知字段、非法值和跨账号访问被拒绝。
- 网页在任务卡下展示待确认字段，支持短文本、数字和金额输入；确认后刷新任务和当前表单。切换任务或提议变化时重置未提交输入，空字段集不展示。自然语言聊天入口仍可继续使用，表单不是每轮必经步骤。

## 验证

- 动态表单专项 API：`6 passed`。
- 后端全量回归：`125 passed`。
- Ruff、compileall、Alembic 迁移升级与前端 TypeScript build 通过。
- 前端 lint 通过，保留 3 条 React Hook warnings（含本次新增 `set-state-in-effect`）。
- 本地数据库已从 `20261104_0016` 升级到 `20261104_0017`。

## 尚未验收

- 尚未接入真实 DeepSeek 输出动态 schema；当前提议由服务端注册能力生成，真实模型只能在后续接入同一 schema 校验入口后验证。
- 尚未完成真实浏览器端登录、刷新后重新读取表单和表单提交联调。
- 当前首版提交 API 直接创建新任务 revision，不自动创建 Run；与自然语言提交的 Run 语义统一仍需后续补齐并单独验收。
- 当前首版只实现 shopping 字段，travel 和多选/日期/地点控件保留在契约类型中但未开放。

## 数据保护与幂等决策

表单 schema、确认值和普通任务条件属于当前用户任务范围内的普通业务数据，按 owner/task/revision 查询，不进入日志或模型外部上下文。表单确认是有副作用的 revision 创建，使用任务当前 revision 做乐观并发，使用 `task_id + client_request_id` 做唯一幂等作用域；重复相同请求复用原 revision，不同值冲突。当前没有外部写入，不宣称跨系统 exactly-once。
