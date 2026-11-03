# 013：网页登录与购物 Agent Run 可视化报告

- 执行日期：2026-11-03
- 状态：**已完成**；核心网页链路、真实 Worker/MCP 终态、双用户隔离、浏览器登出后刷新和独立 SSE 终态补读均已验证
- 范围：网页登录、私有对话、购物任务与条件版本、shopping_agent Run、SSE 状态同步和受限结果展示
- 对应任务：[013 网页登录与购物 Agent Run 可视化](../vibe%20coding/013-shopping-web-workbench.md)

## 1. 已实现

- 将网页初始化占位页替换为 React + TypeScript 购物工作台。
- 使用服务端 HttpOnly Cookie 完成注册、登录、`/api/me` 会话恢复和退出；浏览器不读取或保存 Cookie、API Key 或数据库密码。
- 添加真实私有对话列表和创建对话入口；401 会清空当前私有展示状态。
- 添加购物任务创建表单，提交明确 `goal`、`domain=shopping` 和可选条件；未知条件保持缺失。
- 展示当前 task revision；条件更新通过正式 revision API 完整替换，409 时重新读取服务器最新任务。
- 添加 `shopping_agent` Run 创建、历史列表、版本绑定、状态展示和协作式取消。
- 使用浏览器原生 EventSource 接入私有 SSE；保存最后事件序号，断线后带 `after` 游标重连，并在事件流不稳定时通过有界状态同步读取 Run。
- 终态后读取私有结果接口，展示回答、决策类型、是否委派、MCP 调用次数和模拟来源；失败、取消、排队和运行中均不伪造结果。
- 增加前端重复提交锁，避免快速重复点击产生无意重复 Run。
- 使用响应式 CSS 适配桌面和窄屏；表单、加载、空状态、错误和状态反馈均有明确视觉状态。
- 修复 Run watcher 生命周期：切换 Run、退出和组件卸载时会清理 EventSource、轮询定时器和重连定时器，避免重复后台请求。

## 2. 验证

| 检查 | 结果 |
| --- | --- |
| `npm run build` | 通过 |
| `npm run lint` | 通过 |
| 浏览器匿名入口 | 通过，显示登录/注册工作台 |
| 浏览器注册与登录 | 通过，真实 PostgreSQL 会话 Cookie 建立 |
| 创建私有对话 | 通过，页面读取当前账号对话 |
| 创建购物任务 | 通过，目标、物品、预算、人数、数量和 REV 1 正确显示 |
| 创建 `shopping_agent` Run | 通过，真实 API 返回 queued Run 并显示第 1 版 |
| Worker / Java MCP | 通过；shopping-mcp 在 8101 启动，Worker 真实领取两个 Run，一个因服务未启动准确失败，一个在 MCP 启动后 completed |
| completed 结果 | 通过；浏览器显示真实持久化回答、`delegated_discovery`、委派为是、1 次 MCP 调用和模拟商品来源；本次工具返回空候选，页面没有伪造商品 |
| 刷新恢复 | 通过；浏览器刷新后从服务端重新读取对话、任务、2 个 Run 和 completed 结果 |
| failed 结果 | 通过；浏览器选择失败 Run，显示失败状态和外部调用不确定提示，不渲染结果 |
| 双用户浏览器隔离 | 通过；`web013isolated` 登录后显示空的私有空间，看不到 `web013run` 的对话、任务或 Run |
| 浏览器登出后刷新 | 通过；真实 Chrome 152 使用保留账号的一次性服务端会话登录，页面显示 `web013run`、保留对话/任务和 completed Run；点击“退出”后回到认证页；刷新后仍为登录页，`/api/me` 返回 401，私有任务文本不再出现 |
| 独立 SSE 终态补读 | 通过；使用独立 HTTP 客户端而非浏览器 EventSource，读取 completed Run `a1108268-001a-4f83-9e5c-8d29bbdf1186`：`after=0` 返回 queued/running/completed，`after=2` 仅返回 run.completed，`after=3` 返回空流并关闭；JSON 事件补读一致 |
| SSE / 状态降级 | 通过，页面显示排队中和 Worker 同步提示；EventSource 断开后继续读取状态 |
| 页面文案边界 | 通过，明确说明不自动识别自然语言意图、不代表真实下单 |
| 后端回归 | 012 已有 Python 47 tests、Ruff、compileall、Alembic 检查通过；本轮未修改后端代码 |

## 3. 补充验收与边界

- 浏览器登出后刷新：使用真实 Chrome 152 headless，为保留测试账号 `web013run` 创建一次性服务端会话（未修改密码），登录后页面显示用户名、保留对话/任务和 completed Run；点击“退出”后回到认证页；刷新后仍为登录页，`/api/me` 返回 401，私有任务文本不再出现。登出已吊销临时会话，验收后删除该会话记录。
- 独立 SSE 终态补读：使用独立 HTTP 客户端（非浏览器 EventSource）读取 completed Run：`after=0` 返回 queued/running/completed 三个事件；`after=2` 只返回 run.completed；`after=3` 返回空流并关闭；同时核对 JSON 事件补读只返回终态。没有重复或遗漏。
- 本次补验未新增模型/MCP 调用，复用报告中保留的 completed Run；测试账号、对话、任务和两个 Run 按报告保留在项目库，未删除数据库卷；仅删除一次性会话。
- 本次 completed Run 的工具结果是空候选，页面验证的是诚实的空结果路径；非空候选页面展示仍以 012 的真实非空委派与 013 的通用结果渲染为边界，不在本轮新增商品数据。
- 注册接口本身只创建账号，不自动登录；前端已在注册成功后显式调用登录建立会话。
- 未新增自然语言多轮意图识别、助手消息持久化、候选/方案业务表或 P3 采买规划。

## 4. 运行方式

```bash
# backend
cd backend
DATABASE_URL='postgresql+psycopg://life_buy:postgres@127.0.0.1:55432/life_buy_agent' \
  uv run uvicorn life_agent.main:app --host 127.0.0.1 --port 8000

# web
cd web
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

主链路使用隔离用户名 `web013run` 的浏览器表单登录；补充验收使用该账号的一次性服务端会话，未修改密码，未在代码、报告或日志写入凭据。测试对话、任务和两个 Run 保留在项目库，未删除数据库卷；一次性会话已删除。shopping-mcp、FastAPI、Vite 和 Chrome 在交付前已停止。

## 5. 后续边界

013 已完成。自然语言多轮对话、助手消息持久化、候选/方案业务表和 P3 奖品采买规划另建任务。
