# 账号认证与服务端会话契约

所有路径使用 `/api` 前缀。响应不会包含密码哈希、Cookie 值或会话摘要。

## 用户表示

```json
{
  "id": "019a...",
  "username": "alice",
  "created_at": "2026-11-02T08:00:00Z"
}
```

用户名去除首尾空白并转为小写，只允许 3 至 64 个 ASCII 字母、数字、下划线或连字符。密码长度为 12 至 128 个字符。

## 接口

| 方法与路径 | 请求 | 成功 | 主要失败 |
| --- | --- | --- | --- |
| `POST /api/auth/register` | `username`、`password` | 201 与用户表示 | 409 重复用户名；422 非法输入 |
| `POST /api/auth/login` | `username`、`password` | 200、用户表示与会话 Cookie | 401 凭据错误；422 非法输入 |
| `POST /api/auth/logout` | 无 | 204，吊销当前会话并删除 Cookie | 403 跨站；503 存储不可用 |
| `GET /api/me` | 会话 Cookie | 200 与当前用户表示 | 401 匿名、过期或已吊销；503 存储不可用 |

请求模型拒绝额外字段。客户端提交的 `user_id`、角色或其他身份声明不会进入认证上下文。

## Cookie 与 CSRF

- 默认 Cookie 名为 `life_agent_session`，值是 256 位不可预测秘密；数据库只保存 SHA-256 摘要。
- Cookie 固定 `HttpOnly`、`Path=/`，SameSite 和 Secure 由环境配置。开发 HTTP 默认 `SameSite=Lax; Secure=false`；生产环境启动配置必须 `Secure=true` 并使用 HTTPS。
- 所有状态变更接口检查浏览器 `Origin` 与 `Sec-Fetch-Site`。非受信 Origin 或明确的 cross-site 请求返回 403；无 Origin 的非浏览器同机客户端仍可使用 API。
- 前端部署来源必须加入 `TRUSTED_ORIGINS`。SameSite 是附加防线，不替代服务端来源检查。

## 持久化

- `users` 保存 UUID、规范化用户名、Argon2id 密码哈希、启用状态与创建时间。
- `login_sessions` 保存 UUID、用户外键、会话秘密摘要、服务端到期/吊销时间与创建时间。
- 结构由 Alembic 迁移 `20261102_0001` 管理，不在应用启动时自动建表。