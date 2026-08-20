# CR-030-R1：制度撤销待执行请求读取闭合

状态：`PENDING APPROVAL / BLOCKED-POLICY-REVOCATION-PENDING-READ`

日期：2026-08-19

## 1. 变更原因

`CR-028-R1` 已实现 audit_reviewer 提交撤销确认、system_admin 绑定 request 执行撤销，以及撤销后的 PostgreSQL 即时检索失效。但其两个新增接口均为写接口：request ID 只在提交响应中返回，`PolicyData` 没有待执行 request 字段。跨用户、刷新或重新登录后，system_admin 无法从 Backend 发现待执行请求，当前 Frontend 只能人工粘贴 UUID。

本 CR 只补 management-only 待执行请求读取，不改变两阶段撤销状态机、SoD、检索失效或历史保留，不增加表、迁移、PermissionCode 或自动执行能力。

## 2. 推荐决策摘要

| 决策 | 推荐方案 |
|---|---|
| POLICYREAD-D-001 | 新增按知识库过滤的 pending revocation request keyset 列表 |
| POLICYREAD-D-002 | 仅 `knowledge.approve` audit_reviewer 或 `knowledge.publish` system_admin 可读 |
| POLICYREAD-D-003 | 只投影执行所需元数据，不返回 request/revoke reason 或制度正文 |
| POLICYREAD-D-004 | 列表只读；执行仍必须携带 request ID、当前 Policy row_version 并重新校验 SoD |
| POLICYREAD-D-005 | Frontend 删除 UUID 手工粘贴，不得自动执行或把列表当作锁 |

推荐选择：`recommended-forward-v1 / POLICYREAD-D-001～005`。

## 3. 精确 API 与查询语义

新增：

```text
GET /api/v1/policy-documents/revocation-requests
```

- Query 精确为必填 canonical `knowledge_base_id`、可空 `cursor` 和 `page_size`；`page_size` 默认 50，范围 1～100，未知 Query 固定 422。
- 请求必须先得到数据库重验 Actor，再满足以下其一：`knowledge.approve + audit_reviewer`，或 `knowledge.publish + system_admin`。`read_only` deny-overrides 继续优先；本接口不授予 `knowledge.use`、制度正文检索或问答能力。
- knowledge base 不存在、跨组织、软删除或不可见统一 404 `RESOURCE_NOT_FOUND`。
- Repository 只返回同组织、指定知识库、未软删除且仍为 `published` 的 Policy，其 approval record 同时满足：`action='revoke_request'`、`to_status='revoked'`、`related_record_id IS NULL`，且不存在任何 `action='revoke' AND related_record_id=<request id>` 的执行记录。
- 排序固定为 `requested_at ASC, revocation_request_id ASC`，使用 keyset 分页；不得 OFFSET、全组织枚举、N+1 Policy 查询或 Python 排序。并发执行后下一页不保证历史快照，但每一项在该语句快照内必须仍符合 pending 谓词。
- 本接口只读、无 operation log、不接受 `Idempotency-Key`；成功固定 `Cache-Control: private, no-store`。

## 4. 响应与安全边界

成功 HTTP 200 的 `data` 精确为：

```text
items[]
  revocation_request_id
  policy_id
  policy_code
  policy_name
  policy_row_version
  requested_by
  requested_at
page_size
next_cursor
```

- UUID 均为 canonical lowercase，`policy_row_version` 为正整数十进制字符串，时间戳必须带时区。
- Cursor 为版本化 opaque base64url 值，至少绑定 `knowledge_base_id/requested_at/revocation_request_id`；非法、非 canonical 或跨知识库 Cursor 固定 422 `VALIDATION_ERROR`。
- `next_cursor` 非空时本页必须恰有 `page_size` 项；末页为 null，页内排序严格递增且无重复。
- 响应不得返回 request reason、revoke reason、scope、制度正文、Chunk/Index/Qdrant 身份、来源文件、组织 ID、审批备注、执行 Actor、对象键、哈希或任何 secret。
- 列表项不是执行锁。`POST /policy-documents/{policy_id}/revoke` 仍必须在同一事务锁定 Policy/request，重新验证 row_version、request 归属、未执行、published 状态和请求/执行 Actor 不同；列表中的陈旧项按 CR-028 稳定 409，不能静默刷新后自动执行。

## 5. Frontend 闭环

- `KnowledgeBaseDetailView` 对 audit_reviewer 与 system_admin 加载当前知识库待执行列表，并提供 loading/empty/error/retry/分页/Abort/stale-response 状态。
- audit_reviewer 提交成功后刷新列表并显示“待系统管理员执行”；system_admin 从列表选择请求、填写独立原因后显式执行。
- 删除 system_admin 手工输入 request UUID 的产品路径；request ID 可作为不可编辑的技术标识显示或隐藏，但不得复制制度/请求原文。
- 不自动执行、不批量执行、不轮询触发写入；执行成功或稳定 409 后刷新 Policy 与 pending 列表。
- system_admin 仍无 QA 页面和 `knowledge.use`；audit_reviewer 不能调用 execute。

## 6. API delta 与必须验收

- 当前 checkout 基线为 98 个唯一 `/api/v1` operationId；本 CR `api_delta=+1`，operationId 固定为 `list_pending_policy_revocation_requests_v1`。
- `core_table_delta=0`、`alembic_migration_delta=0`、`permission_code_delta=0`、`operation_log_action_delta=0`。
- PostgreSQL 集成必须覆盖：两角色正例、权限/角色交叉负例、read_only deny、跨组织/跨知识库、已执行排除、Policy 非 published/删除排除、并发 request/execute、keyset 多页和 Cursor 篡改。
- API/Frontend 必须覆盖严格字段、原因/正文不泄露、private no-store、无幂等 Header、loading/empty/error/409/retry/刷新、无自动执行和 system_admin 无 QA 权限。
- OpenAPI 唯一性、Backend unit、Retrieval/Policy PostgreSQL 范围、Frontend typecheck/Vitest/build 必须通过。
- Provider、Qdrant 删除、production、真实数据迁移、部署、提交和推送保持 `NOT_AUTHORIZED/NOT_RUN`。

本 CR 与其他未批准 CR 的 delta 不互相吸收；若与 CR-029 同批批准，两个 delta 各为 +1，最终绝对 operation 数由同步时当前 OpenAPI 重新核对。

## 7. 审批与同步边界

批准角色：产品、架构、数据、Backend/API、Frontend、安全、测试。批准记录必须绑定：

```text
selected_option=POLICYREAD-D-001,POLICYREAD-D-002,POLICYREAD-D-003,POLICYREAD-D-004,POLICYREAD-D-005
cr_revision=CR-030-R1
api_delta=+1
alembic_migration_delta=0
core_table_delta=0
environment_scope=contract+local_test
baseline_manifest_path=docs/request-manifest.md
baseline_manifest_raw_bytes=1281
baseline_manifest_sha256=64a86ad8af13bc1a906e856e325b29feeca738c3515ff6cc3c92582b275ddd2c
baseline_api_v1_operation_count=98
baseline_alembic_head=20260818_027
```

批准前不得修改 active Request、注册 Router、实现 Repository/Service/Frontend 或把本草案视为当前产品行为。批准后必须先同步三份 active Request SSOT 与追踪材料，再实现 local/test。无论是否批准，本 CR 都不授权 Provider、production、真实数据迁移、部署、提交或推送。

`decision_snapshot_sha256`：全文行尾规范化为 LF，定位唯一精确标题 `## 8. 当前状态`，取其前全部行，去除多余尾随空行后保留一个 LF，对 UTF-8 bytes 计算 SHA-256。第 1～7 节任一规范修改必须提升 revision并重新批准。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| CR revision | `CR-030-R1` |
| recommended option | `recommended-forward-v1 / POLICYREAD-D-001～005` |
| decision snapshot | `30e7c0b29a6d44f6c5ef8d9a656d59765b61d97a6527cb22b8df4d78c7aff1b1 / 7072 bytes` |
| approval | `APPROVED；YHBX / product、architecture、data、backend_api、frontend、security、test / POLICYREAD-D-001～005 / 2026-08-19 / direct Codex task approval` |
| Request sync | `COMPLETED；current manifest 8b953ca1d8f82b36ccd856f2db7d166f5709709f368d437f247e170e61812c56 / 1501 bytes` |
| runtime | `IMPLEMENTED AND VERIFIED FOR LOCAL/TEST；Retrieval/Policy 10 / Full 154×2 / Frontend 539 / full OpenAPI 100 PASS` |
| Provider / production / real-data migration | `NOT AUTHORIZED` |
| implementation count note | `signed baseline 98 counted 95 /api/v1 + 3 non-api operations；post-delta expected 97 /api/v1 and 100 full OpenAPI；delta +1 remains exact` |
