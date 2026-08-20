# CR-027-R1：Job HTTP fencing 与审核重试/取消投影闭合

状态：`PENDING APPROVAL / BLOCKED-JOB-HTTP`

日期：2026-08-18

## 1. 变更原因

当前 active runtime 已实现可靠 Job、审核执行、文件重试和审核取消，但 HTTP 合同仍有四个不能安全拼接的差异：

1. `CR-004-R2` 要求 AUDIT-007/008 使用 Job `row_version`；当前 FILE-007 使用文件版本，AUDIT-008 使用 execution 版本，AUDIT-007 尚未注册路由。
2. `CR-004-R2` 的 running 取消要求 execution 保持 `running` 并对外投影 `cancel_requested`；更新的 active `CR-018-R1/RFV1-D-006` 要求 execution 直接进入 `cancelled`，且 execution 状态闭集中不存在 `cancel_requested`。
3. 当前资源详情只返回 `job_id/retryable`，没有 Job `row_version`。Frontend 无权从 execution/file 版本、错误文本或本地计数推导 Job fencing token。
4. 内部 `JobRuntimeRepository.requeue_failed_audit_job()` 已存在，但它是 Maintenance 到期重排 primitive，要求 `next_retry_at <= database_now`；不能直接等同为授权用户 HTTP 重试合同。

本 CR 只闭合上述 HTTP 与事务投影，不改变审核规则、风险结论、Job 状态闭集或自动恢复 Policy。

## 2. 推荐决策摘要

| 决策 | 推荐方案 |
|---|---|
| JOBHTTP-D-001 | 资源详情显式投影只读 Job fencing，不新增通用 Job 枚举接口 |
| JOBHTTP-D-002 | AUDIT-007 新增当前命名空间的显式技术重试入口，同时 CAS execution 与 Job |
| JOBHTTP-D-003 | AUDIT-008 采用 execution 直接 cancelled + Job queued/cancel_requested/cancelled 的双投影 |
| JOBHTTP-D-004 | FILE-007 同时携带 file 与 Job 两个版本，不再把 file 版本冒充 Job 版本 |
| JOBHTTP-D-005 | 同 key/hash replay 对取消返回当前投影，对重试返回首次已提交受理投影 |

推荐选择：`recommended-forward-v1`，全部采用 JOBHTTP-D-001～005。

## 3. 精确合同

### 3.1 统一只读 Job 投影

`AuditExecutionData` 与 `FileListItemData` 在现有 `job_id` 基础上增加 `job` 对象；不存在 Job 时为 null，存在时精确为：

```text
id
status
stage
attempt_no
max_attempts
row_version
retryable
```

- `row_version` 为正整数字符串，唯一来源是 PostgreSQL `async_jobs.row_version`。
- `retryable` 只由 Backend 根据 Job 状态、错误码、attempt/max、冻结 Handler/Retry Policy 和 `next_retry_at <= database_now` 派生。
- 投影不得返回 `input_json/input_hash`、Worker/Lease、错误正文、对象键、Provider 数据或 Secret。
- 本 CR 不新增 `/jobs` 列表/详情路由；资源详情只返回与该资源精确绑定的唯一 Job。

### 3.2 AUDIT-007 技术重试

新增：

```text
POST /api/v1/audit-executions/{execution_id}/retry
```

权限复用 `audits.complete`，要求 `Idempotency-Key`。Body 精确为：

```json
{
  "execution_row_version": "<positive integer>",
  "job_row_version": "<positive integer>",
  "reason": "<trimmed 1..1000>"
}
```

受理事务固定执行：

1. 幂等 advisory lock 与 active organization；
2. audit task → execution → snapshot → 当前 rule/risk/report → Job → 目标 sequence Outbox 的既有锁序；
3. execution 必须为 `failed`、`retryable=true`，Job 必须为同组织 `audit_execute/audit_task_execution`、resource_id 精确命中 execution、status=`failed`、attempt `< max_attempts`、冻结 Handler identity 有效；
4. 两个客户端版本分别匹配 execution 与 Job；任一不匹配返回 409 `RESOURCE_VERSION_CONFLICT` 或 `JOB_VERSION_CONFLICT`；
5. `next_retry_at` 必须已到期。显式 HTTP 动作不绕过 Retry Policy 的退避窗口；未到期返回 409 `JOB_RETRY_NOT_READY`；
6. 同一事务把 execution 与 Job 置为 queued，清空当前失败投影，保持 `attempt_no` 不变，创建且只创建 `event_sequence=attempt_no+1` Outbox，不创建 Step，不删除历史结果；
7. 追加 `audits.execution_retry_queued` operation log，摘要只含 `attempt_no/scheduled_attempt_no/status`。

成功 HTTP 202 的 `data` 精确为：

```text
execution_id
status                 # queued
preserved_results      # true
execution_row_version
job_id
job_status             # queued
attempt_no
scheduled_attempt_no
stage                  # evaluate
job_row_version
```

只有后续 claim 才递增 attempt；技术重试必须复用同一 Job。

### 3.3 AUDIT-008 条件取消

保留当前路径：

```text
POST /api/v1/audit-executions/{execution_id}/cancel
```

Body 更新为：

```json
{
  "execution_row_version": "<positive integer>",
  "job_row_version": "<positive integer|null>",
  "reason": "<trimmed 1..1000>"
}
```

状态矩阵：

| execution 前像 | Job 前像 | `job_row_version` | 提交后 execution | 提交后 Job |
|---|---|---|---|---|
| draft / validating | 不存在 | 必须 null | cancelled | 不创建 |
| queued | queued | 必须匹配 | cancelled | cancelled |
| running | running | 必须匹配 | cancelled | cancel_requested |
| pending_finance_review / pending_audit_review | succeeded | 必须匹配 | cancelled | succeeded，不改写 |

- execution 直接进入 `cancelled`，以 active `CR-018-R1` 为准；不得写入不存在的 execution `cancel_requested`。
- running Worker 在安全检查点只把 Step/Job 从 `cancel_requested` 收敛为 `cancelled`；execution 已 cancelled，必须重验同一 identity，不能重复增加 execution 版本或操作日志。
- 响应 `data` 精确为：

```text
execution_id
execution_status       # cancelled
cancelled_at
execution_row_version
job_id
job_status             # null|cancel_requested|cancelled|succeeded
job_row_version
```

- 同 key/hash replay 不重复写入，必须锁定并重读当前 execution/Job 后返回当前投影；因此 running 取消完成后，replay 可从 `job_status=cancel_requested` 前进为 `cancelled`。
- 不同 hash 返回 409 `IDEMPOTENCY_KEY_REUSED`；execution 或 Job CAS 失败使用各自稳定错误码。

### 3.4 FILE-007 双版本 fencing

现有路径不变。Body 精确更新为：

```json
{
  "file_row_version": "<positive integer>",
  "job_id": "<canonical UUID>",
  "job_row_version": "<positive integer>",
  "reason": "<trimmed 3..500>"
}
```

- file 版本保护资源状态与当前 Job 绑定；Job 版本保护 failed→queued CAS。两者不得互相替代。
- 成功 202 返回现有文件详情加更新后的 `job` 投影；stage 为计划起点，不把 queued Job 的数据库 stage 伪装成 running stage。
- 继续复用同一 Job 和原文件，不创建第二个文件、Job 或对象。

### 3.5 API 与 action delta

- 当前 `/api/v1` operationId 基线为 92。
- 只新增 AUDIT-007 一个 operation，`api_delta=+1`，实现后为 93；AUDIT-008 与 FILE-007 只修改既有合同。
- 新增 action code `audits.execution_retry_queued`；其余 action 不变，`operation_log_action_delta=+1`。
- 不新增 PermissionCode、核心表或通用 Job 路由。

## 4. 数据库、并发与降级边界

- 现有 007/020 状态触发器继续是数据库事实源；若实现需要放宽或新增数据库状态边，必须提升本 CR revision，不能只改 Service。
- HTTP retry/cancel 与 Maintenance recovery 可并发，但同一 execution/Job 最多一个事务成功；失败方返回稳定 409，不重复 Outbox、Step、log 或幂等完成记录。
- running cancel 与 Worker 完成并发时，Job fencing 和 execution 状态前像共同裁决；迟到 Worker 不能从 cancelled execution 产出风险或报告。
- 本 CR 不要求真实数据迁移；若仅为 API/Service/Schema 投影且现有数据库触发器已覆盖，则 `alembic_migration_delta=0`。

## 5. Frontend 合同

- 文件详情和审核详情只从 Backend `job` 投影取得 Job row version/retryable。
- 审核详情在 `failed && job.retryable` 时显示技术重试；在允许状态显示取消。
- UI 必须分别提交 execution/file 与 Job 版本；409 后刷新资源，不自行递增版本。
- “重试页面加载”与“重试业务 Job”使用不同文案和 test id，不能混淆。

## 6. 必须验收

1. OpenAPI 精确请求/响应、93 个唯一 operationId 和覆盖 meta-gate。
2. PostgreSQL 并发：retry/retry、retry/recovery、cancel/Worker complete、cancel/cancel 各只能一个权威结果。
3. queued/running/pending-review/draft 四类取消矩阵与 replay 当前投影。
4. 两种 row version 互换、缺失、陈旧和跨资源 Job ID 全部失败关闭。
5. 重试保留 snapshot/rule/risk 历史、attempt 不提前递增、只生成一个新 Outbox。
6. Frontend 权限、loading/error/409 刷新和不自动重试。
7. 默认离线、Provider 关闭、production 与真实数据迁移 `NOT_RUN`。

## 7. 审批与实施边界

批准角色：产品、架构、数据、Backend/API、Frontend、可靠性、安全、测试。

批准记录必须绑定：

- `selected_option=JOBHTTP-D-001,JOBHTTP-D-002,JOBHTTP-D-003,JOBHTTP-D-004,JOBHTTP-D-005`
- `cr_revision=CR-027-R1`
- exact decision snapshot
- 当前 Request manifest
- `api_delta=+1`
- `environment_scope=contract+local_test`

当前可签基线固定为：

```text
path=docs/request-manifest.md
raw_bytes=1395
raw_sha256=ca90416a73071da90c74c6334a313af045c1b2be53634f098ae5727b911c0177
api_v1_operation_count=92
```

上述任一身份漂移时必须提升 CR revision 并重新生成 snapshot，不能沿用旧签署。

在本 CR 获批并同步 active Request 前，不授权修改 Router/Schema/Service/Frontend 或增加 operation/action。无论是否批准，本 CR 都不授权 Provider、外部网络、production、真实数据迁移、部署、提交或推送。

`decision_snapshot_sha256` 计算规则：行尾规范化为 LF，定位内容完全等于 `## 8. 当前状态` 的唯一标题行，取该行之前的全部行，去除多余尾随空行后保留恰好一个 LF，对 UTF-8 bytes 计算 SHA-256 小写十六进制。第 1～7 节任一规范修改必须提升 revision 并重置签署。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| CR revision | `CR-027-R1` |
| recommended option | `recommended-forward-v1 / JOBHTTP-D-001～005` |
| decision snapshot | `98cae25f9e191e75e4e8ef0809b056ba66c1915d02743f4ff9f7fbfc2a888692 / 10041 bytes` |
| approval | `APPROVED；YHBX / product、architecture、data、backend_api、frontend、reliability、security、test / JOBHTTP-D-001～005 / 2026-08-18 / direct Codex task approval` |
| Request sync | `COMPLETED；active Request 已绑定 CR-027-R1` |
| runtime | `IMPLEMENTED AND VERIFIED FOR LOCAL/TEST；Audit 4 / File 16 / Full 153×2 PASS` |
| Provider / production / real-data migration | `NOT AUTHORIZED` |
| implementation count note | `DELTA +1 IMPLEMENTED；current checkout final count=98；R1 absolute pre-count 92 omitted three already-authorized CR-005 operations and is retained as signed historical input` |
