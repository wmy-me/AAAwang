# 005：私有对话与消息持久化

- 状态：待执行；本文件只定义任务，尚无实现或验收报告
- 所属阶段：P2 任务与对话基础
- 起始分支与提交：`main` / `454fe132630d921e1d5b5cdd9d380344f2e991d3`；执行前核对最新 HEAD，保留之后已有改动
- 前置：[004 账号认证与会话基础](004-auth-foundation.md)及[报告](../reports/004-auth-foundation-report.md)；001–003 的模型/MCP 验证保持可用
- 对应报告：`docs/reports/005-private-conversations-report.md`
- 本任务目标：建立首个真正归属于用户的业务资源，并验证两个账号不能互访

## 1. 问题和先读

004 已提供 PostgreSQL 用户、登录 Cookie、`CurrentUser` 依赖与 Alembic；但尚无私有对话或消息，两个账户各自访问 `/me` 不能证明业务数据隔离。本任务先让“一个账号创建的对话与手工消息只由该账号访问”成立，为后续任务、Agent 和前端对话提供持久化容器。

先读根 `CLAUDE.md`、[任务规则](README.md)、[进度](../progress.md)、[路线图](../roadmap.md)、[项目定位](../overview/project.md)，以及 `backend/src/life_agent/api/dependencies.py`、`api/routes/auth.py`、`db/models.py`、`db/session.py`、`modules/auth/`、`backend/migrations/`、`contracts/rest/auth.md`、`backend/tests/test_auth.py`。初始设计包的会话、消息、任务区分可参考[第 7、10、11 节](../design/生活采买智能体_项目初始设计包.md)，但早期示意字段和接口不是必须照抄的正式契约。

核对最新代码再确定接口和迁移。当前 004 的真实 PostgreSQL 检查使用独立端口/临时卷，不代表当前机器 5432 永远空闲；按环境模板使用本地受信配置，不要求用户把密码贴到任务或报告中。

## 2. 领域边界与本轮范围

- `login_sessions` 是认证会话；本任务的 `conversations` 是用户的**业务对话容器**，二者不能混用。
- 一个 conversation 有唯一 owner（来自服务端 `CurrentUser`），标题、创建/更新时间；message 归属该 conversation，有稳定 ID、发送方标识、文本内容、创建时间和客户端幂等 ID。本轮只接受用户提交的纯文本消息，角色由服务端固定为 `user`，不让客户端伪造 `assistant`、`tool`、用户 ID 或状态。
- 一个对话将来可关联多个任务。本轮**不创建** task、run、方案、执行状态或 LangGraph 检查点；不调用模型或 MCP，不生成助手回复。普通聊天记录不是正式任务条件或候选事实。
- 新增 Alembic 迁移扩展现有用户表关联；明确外键、删除行为、唯一约束与排序索引。数据模型保留可扩展性，但不批量建未来表。所有读写在持久化层按 owner 范围查询，单纯隐藏前端按钮不算隔离。
- 使用现有 Cookie 认证、数据库依赖和同源请求防护。写请求按 004 的受信 Origin/Fetch Metadata 策略执行；不接受前端直接决定 owner_id。

建议首版 REST 接口（最终路径、字段与分页写入 `contracts/rest/conversations.md`）：

| 接口 | 行为 |
| --- | --- |
| `POST /api/conversations` | 当前用户建立空对话，可传短标题 |
| `GET /api/conversations` | 只列出当前用户对话，稳定分页与时间排序 |
| `GET /api/conversations/{id}` | 取得自己的对话概要 |
| `PATCH /api/conversations/{id}` | 修改自己的标题；无权修改 owner |
| `POST /api/conversations/{id}/messages` | 在自己的对话追加一条用户文本，带 `client_message_id` |
| `GET /api/conversations/{id}/messages` | 只读取自己的消息，稳定分页与顺序 |

对不存在和别人的对话使用同类不可枚举结果（例如 404），匿名请求 401。列表只筛选当前用户，不把其他用户的数据先读出后再过滤。内容长度、标题长度、分页上限和输入空白规则应明确并测试，不因错误回显私有正文。

同一会话内 `client_message_id` 重试且正文一致时返回先前消息，不重复插入；相同 ID对应不同内容时返回冲突。幂等判断也必须先校验会话归属。事务更新会话时间与新增消息的提交关系清楚；并发插入时以数据库唯一约束兜底。对话排序和消息顺序不能只靠时间戳相等时的偶然顺序。

## 3. 实施步骤

1. 设计并迁移 `conversations`、`messages`，将 owner 外键连到已存在的 `users`；在 PostgreSQL 实际执行升级及重复升级，核对模型与迁移一致。
2. 实现服务层中按当前用户 ID 限定的查询、写入与消息幂等，API 只传入由认证依赖给出的用户。根据需要使用事务，处理数据库故障与唯一键冲突，避免把异常正文、密码或 Cookie 暴露给客户端。
3. 添加 REST 路由和契约；将写接口接入现有同源请求检查。仅返回用户可见字段，不返回密码哈希或会话摘要。
4. 聚焦测试两个真实登录账户在创建、列表、读取、改标题、追加消息、消息列表、重复提交和伪造 owner/role 等路径的隔离与失败行为。使用真实 PostgreSQL 做至少一次迁移、跨进程或新客户端读取、双用户读写隔离与重试验证；替身/SQLite 测试须单独标注。
5. 运行 Python 聚焦及现有回归、Ruff、编译与迁移检查；更新本任务报告、进度、开发指南和任务索引。未改 Java 或网页时无需重复无关构建。

## 4. 验收标准

| 场景 | 必须观察到的结果 |
| --- | --- |
| 私有创建与持久化 | A、B 各建对话；重新连接或重启 API 后可读取各自的数据 |
| 所有权 | B 用 A 的对话 ID读取、改标题、追加消息或读消息都失败；B 的列表不出现 A 数据；反向同样成立 |
| 受信身份 | 请求体添加 `owner_id`、`user_id` 或伪造 `role=assistant` 被拒，不能改变所有权或制造模型消息 |
| 消息幂等 | 相同客户端 ID与相同正文重试只产生一条消息；相同 ID不同正文明确冲突；B 不得借该 ID探测 A 的资源 |
| 边界与故障 | 未登录为 401；非法长度与分页范围明确失败；跨站写请求被拒；数据库停服不返回伪造成功或泄露连接信息 |
| 回归 | 004 的认证/会话测试与 001–003 的模型/MCP 聚焦测试继续通过；`/api/health` 与既有检查脚本保持可用 |

只有真实 PostgreSQL 双用户隔离和持久化结果通过，才把 005 标记为完成。若真实环境受阻，按“部分完成/受阻”报告，不以 SQLite 或受控替身冒充最终证据。004 认证测试不替代上述资源所有权测试。

## 5. 完成后停止

写 `docs/reports/005-private-conversations-report.md`，记录实际代码起点、迁移、验证命令、真实 PostgreSQL 与测试替身结果、仍未验证的边界；同步 `docs/progress.md`、[任务索引](README.md)、根 README 与运行指南。完成后停止。

后续编号任务再做任务条件与版本、后台 run/Worker、SSE/重连以及网页与 Agent 对话连接。005 不宣称整个 P2 完成，也不把简单保存消息当成 Agent 已有长期记忆或完整对话能力。
