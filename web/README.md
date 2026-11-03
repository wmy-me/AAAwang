# web/ — React 网页

生活采买智能体的网页前端，使用 **React + TypeScript + Vite**，由 npm 管理依赖。

## 当前实现边界

- 提供服务端 Cookie 登录/注册、私有对话、购物任务条件版本、`shopping_agent` Run、取消、SSE 状态同步和受限结果展示。
- `src/api/workbench.ts` 使用浏览器原生 `fetch` 访问现有 `/api` 契约；`src/api/health.ts` 仍保留健康检查封装。
- Vite 开发服务器把 `/api` 代理到 `http://127.0.0.1:8000`，保留路径前缀。
- 使用浏览器原生 `EventSource` 读取私有 Run 事件；私有数据只保留在当前页面内存状态，刷新后重新从服务端读取。
- 未引入 Router、全局状态库、Axios、UI 组件库或地图 SDK；`src/components/` 与 `src/features/` 仍为预留目录。

## 安装与启动

```bash
cd web
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 <http://127.0.0.1:5173>。API 未启动时页面仍可打开，按钮会显示真实的连接失败状态。

## 检查与构建

```bash
cd web
npm run lint
npm run build
```

- Lint：模板当前使用 Oxlint（`npm run lint`）。
- 构建产物：`web/dist/`（不提交）。
- 依赖锁定：`package-lock.json`，Node 主版本记录在根目录 `.nvmrc`。

## 开发代理说明

`vite.config.ts` 中的代理只用于本地开发，不代表生产部署已经完成。代理目标固定为回环地址 `127.0.0.1:8000`。
