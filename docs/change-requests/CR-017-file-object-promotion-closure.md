# CR-017：文件隔离对象与 clean 原件定位闭合

状态：当前 Goal 的前向实现决定（2026-08-13）

## 问题

`20260813_011` 只保存一组不可变 `minio_bucket/minio_object_key`。上传事务把该组写为
quarantine locator，但 `stored+clean` 又要求对象已经位于 originals。直接改写该组会破坏上传身份，
不改写则解析和下载无法从 PostgreSQL 找到安全通过的原件。

## 决定

- 现有 `minio_bucket/minio_object_key` 保持不可变，语义固定为上传时 quarantine locator。
- `files` 增加可空 `original_minio_bucket/original_minio_object_key`；两列只能同时为空或同时非空。
- `uploaded/validating/rejected` 必须没有 originals locator；`stored/archived` 必须有 originals locator。
- 只有 Worker 持有当前 Job Lease、扫描结果为 clean 时，才可在同一 PostgreSQL 事务把文件推进为
  `stored+clean` 并首次写入 originals locator。写入后永久不可改写或清空。
- Worker 先复制到 originals 并逐字节核验；数据库事务失败时补偿删除候选 originals。数据库提交后才
  尝试删除 quarantine。迟到清理失败不回滚已提交 clean 事实，由维护任务按两组定位重试。
- 解析、预览和下载只消费 originals locator；扫描只消费 quarantine locator。

## 用户影响与回滚

安全通过的文件不再长期依赖 quarantine，解析与授权下载有唯一权威对象定位。迁移 downgrade 在
`files` 非空时以 SQLSTATE `55000` 原子拒绝，避免丢失 originals 事实；空表可以安全回滚。

