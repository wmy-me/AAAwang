# 021：自然语言任务与动态表单执行报告

- 状态：已完成
- 任务文档：[021](../vibe%20coding/021-dynamic-task-forms.md)
- 设计依据：[动态表单设计](../design/dynamic-task-forms.md)
- 数据与幂等依据：[数据保护与幂等设计规则](../design/security-and-idempotency.md)

## 已实现

- 新增 `dynamic_form_proposals` 表，按 `task_id + task_revision_id` 保存受限表单提议；同任务的 `client_request_id` 唯一。
- 服务端只生成 shopping 注册字段：`item`、`people`、`quantity`、`budget`，包含控件、标签、原因、单位和范围；模型不能提交 HTML、脚本、工具权限或身份字段。
- `GET /api/tasks/{task_id}/form` 返回当前 task revision 的提议；提议状态和确认值独立于任务条件。
- `POST /api/tasks/{task_id}/form/submit` 校验 proposal、字段白名单、类型、范围、任务归属和 expected revision；确认值在同一事务中创建新的 `TaskRevision`、用户 `Message` 和 `capability_decision` `Run`，返回三者及最新任务。
- 确认值会与当前 revision 的既有条件合并，而不是覆盖 `item`、`people`、`budget` 等已确认字段；表单提交后的 Run 保留原 task goal。
- 相同请求 ID 和相同值返回同一 revision；相同请求 ID 携带不同值被拒绝。过期 revision、未知字段、非法值和跨账号访问被拒绝。
- `GET /api/tasks/{task_id}/form/{proposal_id}` 读取 owner 作用域内的当前或历史表单提议；旧 revision 的提议和 Run 不因新 revision 被覆盖。
- Worker 决策提示同时传入原始任务目标和本轮表单确认消息；表单确认只代表条件确认，是否查询商品仍由模型按目标与条件判断。目标明确要求采购且条件足够时选择商品能力，探索或信息不足时允许直答/追问。
- 模型表单建议是可选建议：空单位会归一化；非法 schema 会被丢弃并记录有界告警，不会使 Run 失败或写入任务条件。
- 模型出现“reason 表示应执行商品发现但 kind=direct 且无能力 ID”的自相矛盾时，Worker 使用共享模型预算做一次有界纠正重试；最终选择仍由模型输出并经服务端可见集校验。
- 网页在任务卡下展示待确认字段，支持短文本、数字和金额输入；确认后刷新任务和当前表单。已完成 Run 的详情会使用传入的 Run 快照加载结果制品，避免表单 Run 在状态更新前漏读商品方案。切换任务或提议变化时重置未提交输入，空字段集不展示。自然语言聊天入口仍可继续使用，表单不是每轮必经步骤。

## 验证

- 动态表单与 capability Worker 专项：`25 passed`。
- 后端全量回归：`133 passed`。
- Ruff、compileall、Alembic 迁移升级与前端 TypeScript build 通过。
- 前端 lint 通过，保留 3 条 React Hook warnings（含本次新增 `set-state-in-effect`）。
- 本地数据库已从 `20261104_0016` 升级到 `20261104_0017`。
- `GET /api/tasks/{task_id}/form/{proposal_id}` 已加入 owner 作用域历史表单读取；跨账号返回 404。

### 真实联调（2026-11-04）

- **真实 DeepSeek 动态 schema**：Run `607a605a-ff30-4e85-a393-0360fba5dae5` 返回 `people/quantity/budget`，`GET /form` 来源为 `deepseek_structured_worker`。128 completion tokens 曾截断多字段 JSON，决策调用已提升到 512 tokens。
- **无预算探索**：任务 `a2ddf82c-56d7-4f38-af81-c75b53d4875c` 的 Run 为 `completed/direct_answer`，模型选择直答并说明预算未定先不调用工具；任务条件仍为 `{}`，没有默认金额。浏览器账号 `cap021n918916` 显示“条件待补充”、待确认字段和“直接回答 · 模型”，无错误。
- **多目标输入**：Run `2ceab72a-f861-4689-b55f-d33997cc2584` 完成 `capability_router`，能力快照同时包含 `map_place_search` 和 `shopping_product_discovery`；任务只写入用户明说的 `item`，未写入未确认预算/人数。浏览器账号 `cap021m34d174` 的同一场景显示模型提议的“班级人数/奖品预算”字段，Run 摘要显示两项能力，无错误。
- **目标修改后重提议**：旧 Run `4088855a-dc3e-478b-ba99-831db364c6cb` 保留旧目标；旧表单 `24caced2-6d4c-468b-a3fe-17a490a38fc4` 在新 revision 后仍返回 200 且字段不变。改为“给办公室同事买咖啡胶囊，预算100元”后，新 Run `792744b1-74a7-4bd4-a6d4-ef88ea79e9ef` 由模型重新提议 `item/quantity`，来源 `deepseek_structured_worker`；revision 历史为 `[1, 2]`，条件仅为用户确认的 `budget=100`。浏览器账号 `cap021r5a92b9` 显示 REV2、当前字段和旧表单 200、revision `[1,2]`。
- **表单确认后的采购方案**：任务 `de7ea69e-5e54-46f0-871a-8e37fd68cc7c` 确认 `quantity=25` 后，既有 `item/people/budget` 被合并保留；Run `299575a3-69f0-4121-8791-e02d80aa7328` 保留原 goal，模型选择 `shopping_product_discovery`，完成 `shopping_agent`，保存 2 个候选并生成 `valid` 方案。浏览器账号 `cap021pwe26352` 在提交后和刷新后均显示条件“彩色铅笔套装 / 预算 ¥200 / 25 人 / 25 件”和 VALIDATED PLAN，无错误。
- **并发、幂等与隔离**：同一 proposal 两个并发提交得到 `201/409`，数据库只有 1 个新 revision、1 条用户消息和 1 个 Run；同键同值顺序重试为 `201/201` 且复用同一消息/Run；同键不同值为 422，过期 revision 为 409；第二账号读取当前/历史表单和提交均为 404。
- **真实模型非确定性处理**：联调中模型偶发把“应执行商品发现”输出为 `kind=direct` 且能力 ID 为空。Worker 对该自相矛盾输出做一次有界纠正重试；最终仍由模型输出和服务端可见集校验决定。非法表单 schema 被丢弃而不使 Run 失败，空 `item.unit` 被归一化。
- **020 回归**：全量 `133 passed`；真实发现仍为 `shopping_product_discovery + map_place_search`；PostgreSQL 中 36 条 `decision/budget` 为 NULL 的旧 Run 可经 `RunResponse` 读取；预算、能力可见性和取消/超时/失租相关测试继续通过。

## 后续任务范围与已知边界

- 当前首版只开放 shopping 的 `item/people/quantity/budget`；travel 和多选/日期/地点控件留给后续独立任务，不影响本任务验收。
- 浏览器验收使用 Playwright 无头 Chromium，未执行有头人工交互；真实模型 schema 输出存在非确定性，已用一次纠正重试缓解但不保证所有措辞稳定命中购物能力。
- 旧表单通过新增 owner 作用域 API 读取；旧 Run 仍通过原有私有 Run API 读取。
- 表单确认不写死“必须查商品”；是否执行能力由模型根据原始目标和条件判断，探索/信息不足时可直答或追问。

## 数据保护与幂等决策

表单 schema、确认值和普通任务条件属于当前用户任务范围内的普通业务数据，按 owner/task/revision 查询，不进入日志或模型外部上下文。表单确认是有副作用的 revision 创建，先合并当前 revision 的既有条件再写入确认值；使用任务当前 revision 做乐观并发和数据库唯一约束，使用 `task_id + client_request_id` 做唯一幂等作用域。顺序重复相同请求复用原 revision；并发相同请求一个成功、一个 409，不产生重复消息或 Run；不同值 422，过期 revision 409。当前没有外部写入，不宣称跨系统 exactly-once。
