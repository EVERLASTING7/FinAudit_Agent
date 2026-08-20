# CR-028-R1：制度撤销、检索失效与历史可见性闭合

状态：`PENDING APPROVAL / BLOCKED-POLICY-REVOCATION-CONTRACT`

日期：2026-08-18

## 1. 变更原因

active 产品要求“撤销制度不用于新检索，历史快照仍可查看”，但当前 runtime 只开放 create → submit → approve → publish：

1. `policy_documents` 已有 `revoked/revoked_at/revoked_by/revoke_reason`，却没有获准状态边、API、权限组合和数据库状态守卫。
2. `policy_approval_records` 可追加任意 action，但没有把审计确认与管理员执行一一关联的字段或约束。
3. 当前 Retrieval allowed-set 与最终 PG recheck 只接受 `published`，因此状态变为 revoked 后已能立即阻断新查询；是否同步删除 Qdrant 点、重建索引或使索引失效尚未冻结。
4. `archived` 已在枚举中，但没有时间、actor、reason、允许源状态或历史可见性合同；不能把 revoked、软删除和 archived 混为同一动作。
5. `system_admin` 拥有 `knowledge.publish` 但没有 `knowledge.use`，当前 Policy 读取依赖和 Frontend 路由使技术执行者无法发现待执行撤销。

本 CR 只闭合 P0 制度撤销；归档继续保留为不可达状态，不新增第 58 张表。

## 2. 推荐决策摘要

| 决策 | 推荐方案 |
|---|---|
| POLICYREV-D-001 | audit_reviewer 发起唯一撤销确认，system_admin 独立执行 |
| POLICYREV-D-002 | 在既有 approval record 增加 related_record_id，一一绑定请求与执行 |
| POLICYREV-D-003 | published → revoked 为 P0 唯一撤销边；archived 不开放 |
| POLICYREV-D-004 | 撤销提交即依靠 PG allow-set/final recheck 失效，不同步伪造 Qdrant 删除成功 |
| POLICYREV-D-005 | 历史审核/索引成员/引用保留；普通新查询和普通知识列表排除 revoked |
| POLICYREV-D-006 | knowledge.publish 获得最小制度元数据读取和技术执行 UI，不获得 knowledge.use 问答能力 |

推荐选择：`recommended-forward-v1 / POLICYREV-D-001～006`。

## 3. 精确状态与职责分离

### 3.1 撤销确认

新增：

```text
POST /api/v1/policy-documents/{policy_id}/revocation-requests
```

- 权限固定为 `knowledge.approve`，并要求实际角色包含 `audit_reviewer`；不新增 PermissionCode。
- Body 精确为 `{row_version,reason}`：row_version 为当前 Policy 正整数字符串，reason 去首尾后 1～1000 字符。
- Policy 必须为同组织、未软删除、`status='published'`。
- 同一 Policy 最多一条 `action='revoke_request'` 记录；重复新 Key 返回 409 `POLICY_REVOCATION_ALREADY_REQUESTED`，相同 Key/hash replay 首次响应。
- 该动作只追加确认记录，不改变 Policy 状态、row_version、索引或 Qdrant。

成功 HTTP 201 的 `data` 精确为：

```text
revocation_request_id
policy_id
status                  # pending_execution
requested_by
requested_at
```

### 3.2 管理员执行

新增：

```text
POST /api/v1/policy-documents/{policy_id}/revoke
```

- 权限固定为 `knowledge.publish`，实际角色必须为 `system_admin`。
- Body 精确为 `{row_version,revocation_request_id,reason}`。
- 锁定组织、Policy 和指定 request 后，重验 request 属于同一 Policy、action=`revoke_request`、to_status=`revoked`，且尚未被任何 execute record 引用。
- 执行 actor 必须不同于请求 actor；角色 deny-overrides 不能被临时授权绕过。
- Policy 必须仍为 `published` 且 row_version 匹配；否则使用稳定 409，不改写 request。
- 同一事务执行 `published → revoked`，写 `revoked_at/revoked_by/revoke_reason`、updated fields、row_version+1，并追加 `action='revoke'`、`related_record_id=<request id>` 的 approval record 与 operation log。

成功 HTTP 200 复用 `PolicyWriteData`，`chunk_set=null`；返回 Policy status=`revoked`。

### 3.3 P0 状态矩阵

本 CR 新增且只新增：

```text
published -> revoked
```

- revoked 为 P0 终态，不允许恢复、重新发布、原地改有效期、soft-delete 或转 archived。
- superseded 的创建/切换仍不是当前 runtime，本 CR 不借撤销补做版本替换。
- archived 状态继续保留在历史枚举中，但 P0 Router/Service/数据库状态机不得进入；归档需后续独立决定。

## 4. 数据库增量

新增 migration，核心表总数保持 57：

1. `policy_approval_records.related_record_id UUID NULL`，自引用 FK；
2. `UNIQUE(related_record_id) WHERE related_record_id IS NOT NULL`；
3. `UNIQUE(policy_document_id) WHERE action='revoke_request'`；
4. approval action/related/nullability constraint：普通 submit/approve/publish 的 related 为 null；revoke_request 为 null；revoke 必须非空且指向同 Policy 的 revoke_request；
5. Policy lifecycle trigger 冻结既有 create/submit/approve/publish 更新和本 CR published→revoked；拒绝直接 SQL archived、revoked 恢复、终态字段漂移和 row_version 非 +1；
6. deferred trigger 在提交前证明 revoke request、execute record 与 Policy revoked 字段一一一致。

升级 preflight：

- 允许现有合法 draft/submitted/business_approved/published/superseded 行；
- 若已有 revoked/archived Policy、未知 approval action、非空 related 候选列或不满足当前生命周期的行，则 SQLSTATE 55000 失败，要求人工前向审查；
- 不自动改写、删除或迁移真实业务数据。

downgrade：存在任一 revoke_request/revoke record、related_record_id 或 revoked Policy 时，在 DDL 前 55000 失败；空证据时可移除本 CR 对象。

## 5. 检索、索引与历史语义

### 5.1 新查询立即失效

- 撤销事务提交后，所有新 Query 的 PG allowed-set、Qdrant must-filter ID 集和最终 PG recheck 均只接受 `status='published'`；revoked Policy、Chunk 和引用不得进入候选、回答或反馈事实。
- query/revoke 并发按最后一次 PG final recheck 的事务可见性线性化；撤销提交后开始或在其后完成 final recheck 的 Query 必须排除该 Policy。

### 5.2 不伪造 Qdrant 删除

- 撤销不在业务事务内调用 Qdrant，不把外部删除成功作为撤销提交前置。
- 既有 active index 可以暂存 revoked Policy 的派生点，但每次检索的 allowed IDs 和最终 PG 审查会排除它们，因此不形成授权泄露。
- 新索引构建只读取 business_approved/published 的获准候选；revoked 不进入新成员。
- 后续显式 index rebuild 可物理清理派生点，但不是撤销正确性的唯一来源。

### 5.3 历史可见性

- audit snapshots、rule/risk/report 引用、历史 `document_index_items`、ChunkSet、Markdown、来源文件和 approval timeline 不删除、不覆盖。
- 普通 `knowledge.use` Policy 列表/详情继续只返回 published；revoked 统一不可见。
- 具有 `knowledge.submit|knowledge.approve|knowledge.publish` 的管理 actor 可读取同组织 revoked 元数据与 approval timeline，但不得因此获得问答或正文检索权限。

## 6. API、Frontend 与 action delta

- 当前 `/api/v1` 基线为 92 个 operationId。
- 本 CR 新增 2 个 operation，`api_delta=+2`；与其他未批准 CR 的 delta 不相互吸收。
- 新增 operation actions：`policy.revocation_requested`、`policy.revoked`，`operation_log_action_delta=+2`。
- `PolicyData` 增加 `revoked_at/revoked_by/revoke_reason` 三字段；非 revoked 必须全 null，revoked 必须全非空。
- Policy list/detail Auth 改为 `knowledge.use OR knowledge.publish`；publisher 只读最小制度元数据，不可调用 QA/RET。
- Frontend：audit_reviewer 在 published Policy 显示“提交撤销确认”；system_admin 显示待执行撤销列表与“执行撤销”；两个动作严格分开，均要求原因、幂等和当前 row_version。
- 不新增 PermissionCode、核心表、自动定时任务或通用审批引擎。

## 7. 必须验收与审批边界

必须验收：

1. request/execute SoD、权限、组织、状态、CAS、幂等和一一关联；
2. 两个请求并发只能一条 request，两个 execute 只能一个成功；
3. 撤销提交后的 allowed-set、Qdrant must-filter 输入与 final recheck 均无 revoked ID；
4. Query 与 revoke 并发无撤销后泄露；
5. 历史审核报告与引用仍可读取；普通 knowledge.use 无法枚举 revoked；
6. migration upgrade/downgrade、直接 SQL 绕过和非空证据阻断；
7. Frontend 两角色、loading/error/409/replay/刷新与无自动执行；
8. Provider、production、真实数据迁移、远程写入为 NOT_RUN/NOT_AUTHORIZED。

批准角色：产品、架构、数据、Backend/API、Frontend、AI/RAG、安全、测试。

批准记录必须绑定：

- `selected_option=POLICYREV-D-001,POLICYREV-D-002,POLICYREV-D-003,POLICYREV-D-004,POLICYREV-D-005,POLICYREV-D-006`
- `cr_revision=CR-028-R1`
- exact decision snapshot
- 当前 Request manifest
- `api_delta=+2`
- `alembic_migration_delta=+1`
- `core_table_delta=0`
- `environment_scope=contract+local_test`

当前可签基线固定为：

```text
path=docs/request-manifest.md
raw_bytes=1395
raw_sha256=ca90416a73071da90c74c6334a313af045c1b2be53634f098ae5727b911c0177
api_v1_operation_count=92
alembic_head=20260818_025
```

任一基线身份漂移必须提升 CR revision。批准并同步 active Request 前，不授权 migration、Router、Service、Frontend 或 action runtime。本 CR 不授权 Provider、外部网络、production、真实数据迁移、部署、提交或推送。

`decision_snapshot_sha256`：行尾规范化为 LF，定位唯一精确标题 `## 8. 当前状态`，取其前全部行，去除多余尾随空行后保留一个 LF，对 UTF-8 bytes 计算 SHA-256。第 1～7 节任一规范修改必须提升 revision并重置签署。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| CR revision | `CR-028-R1` |
| recommended option | `recommended-forward-v1 / POLICYREV-D-001～006` |
| decision snapshot | `7ee397cfb86aece05867e8dc5ba244d4cc6ac1d70d56f551ab8cfa9ca91c9619 / 9798 bytes` |
| approval | `APPROVED；YHBX / product、architecture、data、backend_api、frontend、ai_rag、security、test / POLICYREV-D-001～006 / 2026-08-18 / direct Codex task approval` |
| Request sync | `COMPLETED；active Request 已绑定 CR-028-R1` |
| runtime | `BACKEND/DB IMPLEMENTED；CR-030-R1 successor 已补 management pending request 读取和免手工 UUID Frontend；Retrieval/Policy 10 / Full 153×2 PASS` |
| Provider / production / real-data migration | `NOT AUTHORIZED` |
| implementation count note | `DELTA +2 IMPLEMENTED；current checkout final count=98；R1 absolute pre-count 92 omitted three already-authorized CR-005 operations and is retained as signed historical input` |
