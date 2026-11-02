# db/

数据库接入的预留目录。

后续负责：ORM 会话、数据模型、迁移与事务边界。

本轮不连接数据库，不创建模型或迁移；`infra/compose.yaml` 中的 PostgreSQL 是可选的独立本地服务。
